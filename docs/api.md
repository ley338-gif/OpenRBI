# API

> Status: no OpenAPI/Swagger doc generation is wired up yet beyond FastAPI's automatic `/docs` — this page summarizes the internal-vs-public split and the audit surface. Full endpoint reference is deferred to a later pass; see [development.md](development.md).

## Internal vs. public

- **Public** (through the reverse proxy, `/api/*`): everything under `app/api/` in the backend — auth, sessions, display, admin/*, files, policies.
- **Internal-only** (never exposed publicly, `docs/adr/0004`/`0005`): the Session Agent's entire API (`/v1/sandboxes/*`, `/v1/nodes/self`), authenticated by a shared token (`X-Openrbi-Agent-Token`) distinct from any user-facing credential.

## Audit / Security Events (Phase 18)

`GET /admin/security-events` (ADMIN/SECURITY_REVIEWER) — filterable by `event_type`, `user_id`, `session_id`; paginated (`limit`, default 100, max 500; `offset`). Deliberately **read-only**: there is no `PUT`/`DELETE` anywhere in this router, and nowhere in the codebase issues an `UPDATE`/`DELETE` against the `security_events` table — that absence is the append-only enforcement (docs/security-model.md#audit). The only place a `SecurityEvent` row is ever constructed is `app/services/security_events.py`'s `record_security_event`; verified via a full-codebase search that nothing bypasses it.

Every `metadata_json` payload across the codebase was reviewed end-to-end: every single one is limited to IDs, hashes, filenames, MIME types, and short reason strings — never a password, MFA secret, complete token, or file content, matching the project brief's explicit prohibition.

## Health (Phase 19)

`GET /health` (public, unauthenticated) — pure liveness, always `200 {"status": "ok"}` if the process is up; carries no dependency information.

`GET /admin/health` (ADMIN/SECURITY_REVIEWER) — aggregated dependency health. Response: `{"status": "HEALTHY" | "DEGRADED" | "UNAVAILABLE", "components": [{"name", "status", "detail"}, ...]}` for `api`, `postgres`, `redis`, `session_agent`, `sandbox_runtime`, `browser_image`, `clamav`, `quarantine_storage`. See [architecture.md#health-monitoring-phase-19](architecture.md#health-monitoring-phase-19) for the aggregation rule and why this endpoint (unlike `/health`) is unreachable during a full PostgreSQL outage.
