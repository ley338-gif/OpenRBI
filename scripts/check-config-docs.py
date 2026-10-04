"""Keeps docs/configuration.md in sync with the settings the code reads.

Fails when
- a backend or Session Agent setting (the pydantic Settings classes) is not
  listed, or is listed with a default other than the code's;
- a variable from .env.example or a Compose file interpolation is not listed;
- the page lists a variable that nothing in the repository reads any more.

Parses the config modules with `ast`, so it needs no project dependencies.
"""

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "configuration.md"
SETTINGS = (ROOT / "backend/app/config.py", ROOT / "session-agent/app/config.py")
# Where a documented variable may legitimately be read, besides the Settings.
SOURCES = (
    ".env.example",
    "docker-compose*.yml",
    "scripts/*.sh",
    "scripts/*.py",
    "frontend/*/vite.config.ts",
    "frontend/*/.env.example",
    "frontend/*/src/**/*.ts",
)
ROW = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]*)`\s*\|([^|]*)\|")
INTERPOLATION = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")
ENV_LINE = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=", re.M)


def _literal(node: ast.expr):
    """ast.literal_eval plus arithmetic on numbers (e.g. `8 * 60 * 60`)."""
    if isinstance(node, ast.BinOp):
        left, right = _literal(node.left), _literal(node.right)
        operations = {ast.Mult: lambda a, b: a * b, ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b}
        return operations[type(node.op)](left, right)
    return ast.literal_eval(node)


def settings_fields(path: Path) -> dict[str, object]:
    """{env var name: default} for the module's `Settings` class."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings")
    prefix = ""
    fields: dict[str, object] = {}
    for node in cls.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "model_config" for t in node.targets):
            for keyword in node.value.keywords:  # type: ignore[attr-defined]
                if keyword.arg == "env_prefix":
                    prefix = ast.literal_eval(keyword.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            fields[node.target.id] = _literal(node.value) if node.value is not None else None
    return {f"{prefix}{name.upper()}": default for name, default in fields.items()}


def documented() -> dict[str, str]:
    """{variable: raw Default cell} from the page's tables."""
    rows: dict[str, str] = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match:
            rows[match.group(1)] = match.group(2).strip()
    return rows


def _matches(cell: str, default: object) -> bool:
    if default is None:
        return cell == "*(unset)*"
    if default == "":
        return cell == "*(empty)*"
    code = re.match(r"^`([^`]*)`", cell)
    if not code:
        return False
    value = code.group(1)
    if isinstance(default, bool):
        return value == str(default).lower()
    if isinstance(default, (int, float)):
        try:
            return float(value) == float(default)
        except ValueError:
            return False
    if isinstance(default, (dict, list)):
        return value == json.dumps(default, separators=(",", ":"))
    return value == default


def main() -> None:
    rows = documented()
    errors: list[str] = []

    code_settings: dict[str, object] = {}
    for path in SETTINGS:
        code_settings.update(settings_fields(path))
    for name, default in sorted(code_settings.items()):
        if name not in rows:
            errors.append(f"{name} (Settings) is not documented")
        elif not _matches(rows[name], default):
            errors.append(f"{name}: documented default {rows[name]!r} != code default {default!r}")

    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    deployment_vars = set(ENV_LINE.findall(env_example))
    for compose in ROOT.glob("docker-compose*.yml"):
        deployment_vars.update(INTERPOLATION.findall(compose.read_text(encoding="utf-8")))
    for name in sorted(deployment_vars - set(rows)):
        errors.append(f"{name} (.env.example / Compose) is not documented")

    source_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for pattern in SOURCES
        for path in ROOT.glob(pattern)
        if path.is_file()
    )
    for name in sorted(set(rows) - set(code_settings)):
        if not re.search(rf"\b{name}\b", source_text):
            errors.append(f"{name} is documented but nothing in the repository reads it")

    if errors:
        raise SystemExit("docs/configuration.md is out of sync:\n- " + "\n- ".join(errors))
    print(f"PASS: docs/configuration.md lists all {len(code_settings)} settings and {len(rows)} variables")


if __name__ == "__main__":
    main()
