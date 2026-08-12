# ADR 0011: User/Admin API surface separation via listener mode, not a service split

## Status

Accepted

## Context

Before Productization v0.1.1, every backend router — user-facing (`sessions`, `files`, `display`) and admin-facing (`admin*`, `policies`) — was registered unconditionally in a single FastAPI process (`app/main.py`). Role-based access control (`app/core/deps.py`'s `require_role`) correctly stops an authenticated non-admin user from reaching admin endpoints (a clean `403`), but it does nothing against a different threat: a code-execution-level compromise of the backend process itself. Because there is only one process, holding one set of live credentials (the database connection, the Redis client, the Session Agent's shared bearer token), a compromise of the code path serving user traffic already has everything a compromise of the admin code path would have — RBAC runs *inside* the boundary it's meant to enforce, not across a separate one.

`docs/analysis/productization-v0.1.1-zone-separation.md` examined this in detail before any code was written (per the project's process for this kind of change) and found:
- Most of the properties a User/Admin split is meant to deliver (no direct DB/Redis/Session-Agent/quarantine-filesystem access from any client) already hold today, as a side effect of the single-API-process design, not as a deliberate control.
- The one real gap is the absence of a boundary between the user-serving and admin-serving *code paths* within that process.
- Closing it does not require splitting the codebase, the database, or the Session Agent — see that analysis for the full reasoning this ADR acts on.

`app/api/mfa.py` also mixed one admin-only endpoint (`POST /mfa/admin/users/{id}/reset`) into an otherwise shared/user-facing router — a router-organization issue independent of, but relevant to, this decision.

## Decision

1. Add `OPENRBI_LISTENER_MODE` (`Settings.listener_mode`, a `Literal["user", "admin", "both"]`, default `"both"`) to `backend/app/config.py`. An invalid value fails Settings construction immediately (pydantic `Literal` validation) — the same fail-fast principle as this project's existing secret validators, not a runtime error on first request.
2. Restructure `app/main.py`'s router registration into three explicit functions — `_register_shared_routes`, `_register_user_routes`, `_register_admin_routes` — called conditionally based on `settings.listener_mode`. This is the single, central decision point; no individual endpoint checks the listener mode itself.
3. In `user` mode, admin routers are never imported/registered — a request to `/admin/*` gets FastAPI's own `404` (the route does not exist), not a `403` (the route exists and RBAC rejected the caller). This distinction is the actual point: a process compromised while serving only user traffic has no admin route to call at all, regardless of what credentials it might otherwise extract from its own environment.
4. Split `app/api/mfa.py`'s admin-only reset endpoint into a new `app/api/admin_mfa.py` (`POST /mfa/admin/users/{id}/reset`, unchanged path, unchanged business logic — only the module and router registration changed). `app/api/mfa.py` keeps only enrollment/verification endpoints, which are genuinely shared: both a self-service `USER` and a first-time-enrolling `ADMIN`/`SECURITY_REVIEWER` need them (`/mfa/setup/enroll`+`/mfa/setup/confirm`, called from `app/api/auth.py`'s mandatory-enrollment branch), so `mfa.py` is registered in every listener mode.
5. `both` mode (the default) reproduces MVP 1's exact prior behavior — every router, one process — so Compact/homelab/dev deployments and this project's existing test suite need no changes.

Two throwaway `user`/`admin`-mode container instances of the *unmodified* built image were run side by side with the existing `both`-mode instance to verify: user-mode gets `404` on every admin path and its OpenAPI schema contains no `/admin` paths; admin-mode gets `401` (route exists, auth required) on admin paths and `404` on user-only paths, with no `/sessions`/`/files`/`/display` paths in its OpenAPI schema; `both`-mode is unchanged; an invalid `OPENRBI_LISTENER_MODE` value fails container startup with a clear error. See `scripts/test-listener-modes.sh`.

## Alternatives Considered

- **Full microservice split (separate repositories/codebases for a "User API" and "Admin API")** — would deliver the same trust-boundary property but at a cost the analysis found unjustified for this project's stated scope (homelab/KMU-first, no Kubernetes/service-mesh, single maintained codebase): every future change to shared logic (session lifecycle, the file pipeline, quarantine) would need to land in two places, or a shared library would need to be extracted and versioned across two deployables. Rejected — the listener-mode flag delivers the process-level boundary without this cost, because both "instances" are the same running artifact.
- **RBAC alone, no further preparation** — the status quo before this ADR. Rejected because it does not address the process-compromise threat (see Context) at all, only the authenticated-non-admin-user threat, which was already fully handled.
- **Separate Postgres roles / Session Agent token scopes per listener now** — would close the *remaining* residual risk (a compromised process using its own DB/Session-Agent credentials beyond what its own routes need) more completely. Explicitly deferred: no code changes to database roles or Session Agent authentication are part of this decision. Tracked as a follow-up hardening item, not blocking Productization v0.1.1.

## Consequences

- A future User Portal and Admin Portal can each be built from day one against a `user`-mode or `admin`-mode backend instance's own (smaller, listener-specific) OpenAPI schema, rather than against the full combined surface — avoiding a later, more expensive retrofit once both frontends already assume a single origin/schema.
- Compact deployments (the only kind that exist today) are unaffected — `both` is the default and reproduces prior behavior exactly, verified by the full existing `backend/tests/` suite passing unchanged.
- The Session Agent's shared static bearer token and the single Postgres connection are still available, at the credential level, to whichever listener-mode process holds them — this ADR closes the *route-existence* boundary, not the *credential-scoping* boundary. See the "Alternatives Considered" note above; that's deliberately out of scope here.
- `docs/architecture.md`, `docs/security-model.md`, and `docs/deployment.md` are updated alongside this ADR to describe what's implemented (listener modes exist, work, and are tested) versus what remains a documented-but-not-yet-built Segmented deployment profile (see [ADR 0012](0012-compact-vs-segmented-deployment.md)).
