"""Generates docs/api-reference.md from the backend's and the Session Agent's
own FastAPI route tables, so the reference cannot drift from the code.

    python scripts/generate-api-reference.py           # rewrite the file
    python scripts/generate-api-reference.py --check   # fail if it is stale (CI)

The two components have separate dependency locks, so each app is imported
in its own interpreter: --backend-python and --agent-python (default: the
interpreter running this script). Each child prints its route table as JSON
(--introspect backend|agent); this process renders the Markdown.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "api-reference.md"

# Routes that need no login session or agent token. Each one is closed by its
# own mechanism, stated here; the generator refuses to run when a new route
# without auth dependencies has no entry, so a public endpoint is always a
# deliberate, documented decision.
SELF_AUTHENTICATING = {
    ("GET", "/health"): "public (liveness only)",
    ("GET", "/setup/status"): "public (reports only whether setup is required)",
    ("POST", "/setup/admin"): "console setup token, until setup completes",
    ("POST", "/setup/mfa/confirm"): "MFA token from `POST /setup/admin`",
    ("POST", "/auth/login"): "credentials in the body",
    ("POST", "/auth/mfa/verify"): "MFA token from `POST /auth/login`",
    ("POST", "/mfa/setup/enroll"): "MFA token from `POST /auth/login`",
    ("POST", "/mfa/setup/confirm"): "MFA token from `POST /auth/login`",
    ("POST", "/admin/nodes/enroll"): "single-use node enrollment token",
}

# Endpoint summaries are derived from the handler's name; these words keep
# their spelling instead of being lowercased.
KEEP_CASE = {"mfa": "MFA", "ldap": "LDAP", "id": "ID", "csrf": "CSRF", "totp": "TOTP", "ws": "WebSocket"}


# --- introspection (runs inside the component's own interpreter) ----------------


def _summary(name: str) -> str:
    name = name.strip("_").removesuffix("_endpoint")
    words = [KEEP_CASE.get(word, word) for word in name.split("_")]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def _walk(dependant):
    stack = [dependant]
    while stack:
        current = stack.pop()
        if current.call is not None:
            yield current.call
        stack.extend(current.dependencies)


def _flat_routes(routes):
    """(path, methods, name, route) for every route, with included routers
    expanded. FastAPI >= 0.141 keeps an included router as one lazy entry in
    app.routes; iter_route_contexts resolves the effective (prefixed) paths.
    """
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # older FastAPI: include_router copies the routes
        for route in routes:
            yield route.path, getattr(route, "methods", None), route.name, route
        return
    for context in iter_route_contexts(routes):
        route = context.original_route
        # A WebSocket route's context has no path/name; the route itself
        # carries the full (already prefixed) path.
        yield context.path or route.path, context.methods, context.name or route.name, route


def _introspect(component: str) -> dict:
    import inspect

    os.environ.setdefault("OPENRBI_ENVIRONMENT", "development")
    if component == "backend":
        sys.path.insert(0, str(ROOT / "backend"))
        os.chdir(ROOT / "backend")
        os.environ["OPENRBI_LISTENER_MODE"] = "both"
        os.environ.setdefault("OPENRBI_SESSION_AGENT_API_TOKEN", "api-reference-generator")
        os.environ.setdefault("OPENRBI_TOTP_SECRET_ENCRYPTION_KEY", "00" * 32)
        os.environ.setdefault("OPENRBI_CSRF_SECRET_KEY", "api-reference-generator")
        import app.main as main
        from app.core.deps import get_current_user
        from fastapi import FastAPI

        listeners: dict[tuple[str, str], str] = {}
        for listener, register in (
            ("shared", main._register_shared_routes),
            ("user", main._register_user_routes),
            ("admin", main._register_admin_routes),
        ):
            scratch = FastAPI()
            register(scratch)
            for path, methods, _name, _route in _flat_routes(scratch.routes):
                for method in methods or {"WEBSOCKET"}:
                    listeners[(method, path)] = listener
        application = main.app
    else:
        sys.path.insert(0, str(ROOT / "session-agent"))
        os.chdir(ROOT / "session-agent")
        import app.main as main

        get_current_user = None
        listeners = {}
        application = main.app

    routes = []
    for path, methods, name, route in _flat_routes(application.routes):
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue  # OpenAPI/docs routes FastAPI adds itself
        # Every gate on the route must pass, so router- and route-level
        # role gates intersect and the strictest agent scope wins.
        roles: set[str] | None = None
        scopes: set[str] = set()
        session = False
        for call in _walk(dependant):
            qualname = getattr(call, "__qualname__", "")
            if qualname.startswith("require_role.<locals>"):
                allowed = set(inspect.getclosurevars(call).nonlocals["allowed_role_names"])
                roles = allowed if roles is None else roles & allowed
            elif qualname.startswith("require_control_plane_token.<locals>"):
                scopes.add(inspect.getclosurevars(call).nonlocals["required_scope"])
            elif call is get_current_user:
                session = True
        access: dict | None = None
        if roles is not None:
            order = ["ADMIN", "SECURITY_REVIEWER", "USER"]
            access = {"roles": sorted(roles, key=lambda role: order.index(role) if role in order else len(order))}
        elif scopes:
            access = {"agent_scope": "admin" if "admin" in scopes else "user"}
        elif session:
            access = {"session": True}
        for method in sorted(methods or {"WEBSOCKET"}):
            if method == "HEAD":
                continue
            routes.append(
                {
                    "method": method,
                    "path": path,
                    "summary": _summary(name),
                    "access": access,
                    "listener": listeners.get((method, path)),
                }
            )
    return {"routes": routes, "openapi": application.openapi()}


# --- rendering -----------------------------------------------------------------


def _ref_name(schema: dict) -> str | None:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    return None


def _type(schema: dict | bool) -> str:
    if not isinstance(schema, dict):
        return "any"  # e.g. additionalProperties: true
    name = _ref_name(schema)
    if name:
        return f"`{name}`"
    if "anyOf" in schema:
        parts = [_type(option) for option in schema["anyOf"] if option.get("type") != "null"]
        optional = any(option.get("type") == "null" for option in schema["anyOf"])
        return " or ".join(parts + (["null"] if optional else []))
    if schema.get("type") == "array":
        return f"list of {_type(schema.get('items', {}))}"
    if "enum" in schema:
        return " \\| ".join(f"`{value}`" for value in schema["enum"])
    if "const" in schema:
        return f"`{schema['const']}`"
    fmt = schema.get("format")
    kind = schema.get("type", "any")
    if kind == "object" and "additionalProperties" in schema:
        return f"map of {_type(schema['additionalProperties'])}"
    return {"uuid": "uuid", "date-time": "datetime", "binary": "file"}.get(fmt, kind)


def _constraints(schema: dict) -> str:
    target = schema
    if "anyOf" in schema:
        target = next((option for option in schema["anyOf"] if option.get("type") != "null"), schema)
    low = target.get("minimum", target.get("exclusiveMinimum"))
    high = target.get("maximum", target.get("exclusiveMaximum"))
    bits = []
    if low is not None and high is not None:
        bits.append(f"{low}–{high}")
    elif low is not None:
        bits.append(f"≥ {low}")
    elif high is not None:
        bits.append(f"≤ {high}")
    if "maxLength" in target:
        bits.append(f"max {target['maxLength']} chars")
    return ", ".join(bits)


def _parameters(operation: dict, components: dict) -> str:
    rendered = []
    for parameter in operation.get("parameters", []):
        if parameter["in"] not in ("query", "header"):
            continue
        if parameter["name"].lower() == "x-openrbi-agent-token":
            continue  # every agent route; explained in the section intro
        schema = parameter.get("schema", {})
        detail = [_type(schema)]
        limits = _constraints(schema)
        if limits:
            detail.append(limits)
        if "default" in schema and schema["default"] not in (None, ""):
            detail.append(f"default `{json.dumps(schema['default'])}`")
        where = "header " if parameter["in"] == "header" else ""
        required = ", required" if parameter.get("required") else ""
        rendered.append(f"{where}`{parameter['name']}` ({', '.join(detail)}{required})")
    body = operation.get("requestBody", {}).get("content", {})
    for media_type, content in body.items():
        schema = content.get("schema", {})
        if media_type == "multipart/form-data":
            # FastAPI names the form model Body_<operation id>; show its fields instead.
            form = components.get(_ref_name(schema) or "", schema)
            fields = [
                f"`{field}` ({'file' if 'contentMediaType' in spec or spec.get('format') == 'binary' else _type(spec)})"
                for field, spec in form.get("properties", {}).items()
            ]
            rendered.append("multipart form: " + ", ".join(fields))
        else:
            rendered.append("body " + _type(schema))
    return "<br>".join(rendered) or "—"


def _response(operation: dict) -> str:
    for code, response in sorted(operation.get("responses", {}).items()):
        if not code.startswith("2"):
            continue
        schema = response.get("content", {}).get("application/json", {}).get("schema")
        if not schema or schema == {}:
            return f"`{code}`"
        return f"`{code}` {_type(schema)}"
    return "—"


_USED_EXCEPTIONS: set[tuple[str, str]] = set()


def _access(route: dict) -> str:
    access = route["access"]
    if access is None:
        key = (route["method"], route["path"])
        _USED_EXCEPTIONS.add(key)
        if key not in SELF_AUTHENTICATING:
            raise SystemExit(
                f"{route['method']} {route['path']} has no auth dependency and no entry in "
                "SELF_AUTHENTICATING (scripts/generate-api-reference.py) — say how it is protected"
            )
        return SELF_AUTHENTICATING[key]
    if "roles" in access:
        return ", ".join(f"`{role}`" for role in access["roles"])
    if "agent_scope" in access:
        return f"agent token, `{access['agent_scope']}` scope"
    return "any logged-in user"


def _section_key(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "/"
    if parts[0] in ("admin", "v1") and len(parts) > 1:
        return f"/{parts[0]}/{parts[1]}"
    return f"/{parts[0]}"


def _render_routes(routes: list[dict], openapi: dict, *, listener_column: bool) -> list[str]:
    sections: dict[str, list[dict]] = {}
    for route in routes:
        sections.setdefault(_section_key(route["path"]), []).append(route)
    lines: list[str] = []
    for key in sorted(sections):
        lines += [f"### `{key}`", ""]
        header = "| Endpoint | Access |" + (" Listener |" if listener_column else "") + " Parameters | Success response |"
        lines += [header, "|---|---|" + ("---|" if listener_column else "") + "---|---|"]
        for route in sorted(sections[key], key=lambda r: (r["path"], r["method"])):
            operation = openapi.get("paths", {}).get(route["path"], {}).get(route["method"].lower(), {})
            endpoint = f"`{route['method']} {route['path']}`<br>{route['summary']}"
            if route["method"] == "WEBSOCKET":
                parameters, response = "WebSocket (noVNC/RFB)", "—"
            else:
                components = openapi.get("components", {}).get("schemas", {})
                parameters, response = _parameters(operation, components), _response(operation)
            row = f"| {endpoint} | {_access(route)} |"
            if listener_column:
                row += f" {route['listener']} |"
            lines.append(row + f" {parameters} | {response} |")
        lines.append("")
    return lines


def _render_schemas(openapi: dict) -> list[str]:
    lines = []
    schemas = openapi.get("components", {}).get("schemas", {})
    for name in sorted(schemas):
        schema = schemas[name]
        properties = schema.get("properties")
        if not properties or name.startswith("Body_"):
            continue  # Body_* are FastAPI's form models, shown inline above
        required = set(schema.get("required", []))
        fields = []
        for field, field_schema in properties.items():
            marker = "" if field in required else "?"
            fields.append(f"`{field}{marker}` {_type(field_schema)}")
        lines.append(f"- **{name}**: " + ", ".join(fields))
    return lines


def render(backend: dict, agent: dict) -> str:
    lines = [
        "# API reference",
        "",
        "<!-- Generated by scripts/generate-api-reference.py from the backend's and the Session Agent's",
        "     route tables. Do not edit by hand: change the code and run the script. CI fails when this",
        "     file is out of date. -->",
        "",
        "Every HTTP route of the backend and the Session Agent, generated from the code. For what the",
        "endpoints mean and how they fit together, see [api.md](api.md) and the guides it links. Full",
        "JSON schemas are also served by a running backend at `/api/openapi.json`.",
        "",
        "- **Paths** are the backend's own. Through the reverse proxy they are under `/api/`, e.g.",
        "  `POST /auth/login` is `https://<host>/api/auth/login`.",
        "- **Access**: `ADMIN` / `SECURITY_REVIEWER` / `USER` are roles; \"any logged-in user\" needs a",
        "  session cookie (`openrbi_session`) of any role. A state-changing request also needs the",
        "  CSRF header ([security-model.md](security-model.md#csrf-protection-rbi-post-003)).",
        "- **Listener**: which `OPENRBI_LISTENER_MODE` serves the route — `shared` (every mode), `user`",
        "  (`user` and `both`) or `admin` (`admin` and `both`); see",
        "  [ADR 0011](adr/0011-user-admin-listener-separation.md).",
        "- A field marked `?` in [Schemas](#schemas) is optional.",
        "",
        "## Backend",
        "",
    ]
    lines += _render_routes(backend["routes"], backend["openapi"], listener_column=True)
    lines += [
        "## Session Agent (internal)",
        "",
        "Reachable only from the control plane, never through the reverse proxy",
        "([ADR 0004](adr/0004-separate-session-agent.md)). Requests carry the `X-Openrbi-Agent-Token`",
        "header; the `admin` scope is a superset of `user`",
        "([ADR 0025](adr/0025-segmented-credential-scoping.md)).",
        "",
    ]
    lines += _render_routes(agent["routes"], agent["openapi"], listener_column=False)
    lines += ["## Schemas", "", "### Backend", ""]
    lines += _render_schemas(backend["openapi"])
    lines += ["", "### Session Agent", ""]
    lines += _render_schemas(agent["openapi"])
    stale = sorted(set(SELF_AUTHENTICATING) - _USED_EXCEPTIONS)
    if stale:
        raise SystemExit(f"SELF_AUTHENTICATING lists routes that are gone or now require auth: {stale}")
    return "\n".join(lines).rstrip("\n") + "\n"


def _run_child(python: str, component: str) -> dict:
    result = subprocess.run(
        [python, str(Path(__file__).resolve()), "--introspect", component],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"introspecting the {component} failed:\n{result.stderr}")
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if docs/api-reference.md is out of date")
    parser.add_argument("--backend-python", default=sys.executable)
    parser.add_argument("--agent-python", default=sys.executable)
    parser.add_argument("--introspect", choices=("backend", "agent"), help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.introspect:
        print(json.dumps(_introspect(args.introspect)))
        return

    text = render(_run_child(args.backend_python, "backend"), _run_child(args.agent_python, "agent"))
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current.replace("\r\n", "\n") != text:
            raise SystemExit(
                "docs/api-reference.md is out of date — run: python scripts/generate-api-reference.py"
            )
        print("PASS: docs/api-reference.md matches the route tables")
        return
    OUTPUT.write_bytes(text.encode("utf-8"))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
