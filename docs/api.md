# API

> Status: no OpenAPI/Swagger doc generation is wired up yet beyond FastAPI's automatic `/docs` — this page summarizes the internal-vs-public split and the audit surface. Full endpoint reference is deferred to a later pass; see [development.md](development.md).

## Internal vs. public

- **Public** (through the reverse proxy, `/api/*`): everything under `app/api/` in the backend — auth, sessions, display, admin/*, files, policies.
- **Internal-only** (never exposed publicly, `docs/adr/0004`/`0005`): the Session Agent's entire API (`/v1/sandboxes/*`, `/v1/nodes/self`), authenticated by a shared token (`X-Openrbi-Agent-Token`) distinct from any user-facing credential.

## Audit / Security Events (Phase 18)

`GET /admin/security-events` (ADMIN/SECURITY_REVIEWER) — filterable by `event_type`, `user_id`, `session_id`; paginated (`limit`, default 100, max 500; `offset`). Deliberately **read-only**: there is no `PUT`/`DELETE` anywhere in this router, and nowhere in the codebase issues an `UPDATE`/`DELETE` against the `security_events` table — that absence is the append-only enforcement (docs/security-model.md#audit). The only place a `SecurityEvent` row is ever constructed is `app/services/security_events.py`'s `record_security_event`; verified via a full-codebase search that nothing bypasses it.

Every `metadata_json` payload across the codebase was reviewed end-to-end: every single one is limited to IDs, hashes, filenames, MIME types, and short reason strings — never a password, MFA secret, complete token, or file content, matching the project brief's explicit prohibition.

## Admin user management

`GET /admin/users` (ADMIN) returns a paginated object with `items`, `total`, `offset`, `limit`, real role names, and global account statistics. Supported query parameters are `search` (username), `role`, `group_id`, `status` (`ACTIVE`/`DISABLED`), `auth_source` (`LOCAL`/`LDAP`), `mfa` (`ENABLED`/`NOT_ENABLED`), `sort_by` (`username`, `role`, `status`, `created_at`), `sort_dir`, `offset`, and `limit` (maximum 100). Each item includes its authentication source and latest successful login time derived from audit events. The endpoint joins roles and loads group names and login times in bounded aggregate queries rather than one query per user.

All user mutation endpoints remain ADMIN-only. `POST /admin/users/{id}/reset-password` is only valid for LOCAL accounts; LDAP credentials remain directory-managed. Self-disable, disabling the final active administrator, and removing the final active administrator's ADMIN role are rejected by the backend.

### LDAP administration

`GET /admin/ldap/config`, `PUT /admin/ldap/config`, and `POST /admin/ldap/test` are `ADMIN`-only. Configuration responses never contain the bind password; `bind_password_configured` only reports whether an encrypted secret exists. Omitting or submitting an empty `bind_password` during an update preserves the existing secret. The server accepts only `ldap://` with StartTLS or `ldaps://` without StartTLS, requires a non-empty base DN, and requires `{username}` in the user search filter. The test endpoint is stateless and returns sanitized per-step results for connection/TLS, service bind, base search, and optional user/group lookup. It never persists the candidate configuration.

### Policy overview

`GET /admin/policies` is `ADMIN`-only and returns `items`, filtered `total`, `offset`, `limit`, and global statistics. It accepts `search` (name/description), `policy_type`, `status_filter` (`PUBLISHED` or `DRAFT`), `usage` (`IN_USE` or `UNASSIGNED`), `sort_by` (`name`, `policy_type`, `status`, `updated_at`), `sort_dir`, `offset`, and `limit` (maximum 100). “In use” means at least one `GroupPolicy` assignment. Each item reports the current published version, whether any draft exists, version count, assigned group names, last policy/version change, and the latest version author when available. `POST /admin/policies` additionally accepts an optional description.

`GET /admin/groups-overview` (ADMIN) supplies the paginated Groups operations view. It accepts `search` (name/description), `policy_id`, `sort_by` (`name`, `members`, `created_at`), `sort_dir`, `offset`, and `limit` (maximum 100), and returns aggregate totals plus policy names without per-group queries. Existing `GET /admin/groups` remains the compact unpaginated selector contract used by user and policy forms. Group create/delete and policy attachment endpoints remain unchanged and ADMIN-authorized.

`GET /admin/sessions` (ADMIN/SECURITY_REVIEWER) returns a paginated session operations response with global KPIs and actual lifecycle-state values. It supports `search` (session UUID/username), `session_status`, `worker_id`, `since`, `sort_by` (`started_at`, `duration`, `username`, `status`), `sort_dir`, `offset`, and `limit` (maximum 100). User and worker information are joined in one query. Session detail and lifecycle-action authorization remain unchanged; `kill` is ADMIN-only.

### Worker overview

`GET /admin/nodes/overview` (ADMIN/SECURITY_REVIEWER) returns a paginated worker inventory plus global worker KPIs. It supports `search` (hostname), `health`, `node_status`, `sort_by` (`hostname`, `health`, `cpu`, `ram`, `sessions`, `heartbeat`), `sort_dir`, `offset`, and `limit` (maximum 100). Health is computed by the central worker-health service; the endpoint does not derive a second UI-only health model. Worker state mutations remain ADMIN-only.

## Health (Phase 19)

`GET /health` (public, unauthenticated) — pure liveness, always `200 {"status": "ok"}` if the process is up; carries no dependency information.

`GET /admin/health` (ADMIN/SECURITY_REVIEWER) — aggregated dependency health. Response: `{"status": "HEALTHY" | "DEGRADED" | "UNAVAILABLE", "components": [{"name", "status", "detail"}, ...]}` for `api`, `postgres`, `redis`, `session_agent`, `sandbox_runtime`, `browser_image`, `clamav`, `quarantine_storage`. See [architecture.md#health-monitoring-phase-19](architecture.md#health-monitoring-phase-19) for the aggregation rule and why this endpoint (unlike `/health`) is unreachable during a full PostgreSQL outage.
