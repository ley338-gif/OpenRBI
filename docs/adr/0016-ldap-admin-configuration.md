# ADR 0016: Admin-portal-managed LDAP configuration

## Status

Accepted

## Context

Roadmap B1 (ADR 0015) shipped LDAP authentication configured entirely via `OPENRBI_LDAP_*` environment variables — the only way to enable, reconfigure, or disable it was editing `.env`/deployment config and restarting the backend, and there was no way to verify a configuration works before committing to it, no admin-portal visibility into the current setup, and no admin-portal-managed group→role mapping (`Settings.ldap_group_role_mapping` was env-only, a JSON blob).

Roadmap B1.8 requires an OpenRBI administrator to configure, test, save, and enable/disable LDAP entirely through the web Admin Portal, with no SSH/`.env` editing needed for normal operation. `Settings` (`app/config.py`) is an `@lru_cache`d object read once at process start — it cannot be hot-reloaded, so a runtime-configurable LDAP setup needs a persistence path the running application can read per-request, not just env vars.

## Decision

### Reuse, not duplicate

No second LDAP client or authentication implementation. `LdapAuthProvider` (`app/core/auth_providers/ldap.py`) is decoupled from `app.config.get_settings()` via a new `LdapConnectionConfig` dataclass, constructed either from `Settings` (the pre-existing env-var path, `config_from_settings()`) or from the new persisted row (`config_from_row()`) — both in `app/services/ldap_config_service.py`. `LdapAuthProvider` itself does not know or care which source built its config. The same class also gains `test_connection()`, reusing the identical connection/bind/search code path a real login exercises — the admin portal's "Test LDAP configuration" feature is never a second, parallel LDAP client that could drift from what a real login actually does.

### Single-row persisted config, not a generic settings platform

`LdapConfig` (`app/models/ldap_config.py`) is a single-row table: a fixed, well-known UUID primary key (`LDAP_CONFIG_ID`) is a structural guarantee of "at most one row that matters," without a unique-constraint-plus-application-check dance or a generic key/value settings table the task explicitly cautioned against building. The admin portal manages exactly one LDAP configuration, matching what B1 itself supports (one directory, one group→role mapping) — not named profiles or multiple simultaneous directories, which is out of scope.

### Priority: DB-authoritative-once-it-exists, env vars as bootstrap/fallback only

`get_effective_ldap_config()` (`ldap_config_service.py`): if a `ldap_configs` row exists at all, it is authoritative **in full** — never merged field-by-field with the environment, never "env fills in an empty DB field." If no row exists yet, the pre-existing `OPENRBI_LDAP_*` environment variables are used unchanged, so a fresh install or a deployment that hasn't touched the admin UI keeps working exactly as Roadmap B1 shipped it. This is deliberately simple to reason about: there is exactly one question ("does a row exist?"), not a cascading precedence list per field.

`app/api/auth.py`'s `/auth/login` resolves `get_effective_ldap_config(db)` per request instead of reading the module-level cached `settings.ldap_enabled` — the only change to the real login path, and it is a resolution-source change only; the fail-closed behavior, exact-username-match reconciliation, and local-role-authority rules from ADR 0015 are all unchanged.

### Secret handling

The bind password is encrypted at rest reusing `app/core/crypto.py`'s existing Fernet helpers (`encrypt_secret`/`decrypt_secret`, keyed by `OPENRBI_TOTP_SECRET_ENCRYPTION_KEY`) — one encryption-at-rest key for the whole project, not a second one introduced for this feature.

It is never returned by any API response: `LdapConfigResponse` (`app/api/schemas/admin_ldap.py`) has no password field at all, structurally, only `bind_password_configured: bool`. `LdapConfigUpdateRequest.bind_password` is `str | None`, and the update endpoint treats "omitted" and "empty string" identically — both mean "keep the existing stored secret." Only a non-empty, explicitly submitted value ever replaces it. It is never logged and never appears in an audit event; `LDAP_CONFIG_CHANGED` metadata records only `server_uri`, `use_starttls`, `base_dn`, and a `bind_password_changed: bool` flag, never the value itself.

Errors returned from `test_connection()` are passed through `_friendly_ldap_error()`, which maps known `python-ldap` exception types to admin-readable strings (e.g. "TLS certificate validation failed", "Could not reach the LDAP server") — never a raw exception message or stack trace in an HTTP response body. The full exception is still available to server-side logs for real debugging, just not surfaced to the API caller.

### Edit → Test → Save → Activate, without a second draft/pending-config state machine

`POST /admin/ldap/test` is fully stateless: it never reads or writes the `ldap_configs` row, taking a complete candidate configuration directly in the request body. An admin can try out any configuration, including one that would replace an already-working saved setup, with zero risk of it being persisted just by testing it.

`PUT /admin/ldap/config`, when the submitted config would leave LDAP `enabled=true`, re-runs the exact same `test_connection()` against the *candidate* configuration before writing anything. A failing test returns `422` with the structured per-step failure detail and the request is rejected — the existing row, if any, is left completely untouched. This satisfies "a failed test/save can never destroy the active config" with a stricter validation gate on the single write path, rather than a separate pending/draft-config table and a second activation step — the latter was considered and rejected as unnecessary complexity for a single-row, single-directory configuration surface.

Saving with `enabled=false` never requires a passing test — an admin must be able to save a config that isn't fully correct yet (to iterate on it) as long as they aren't asking the system to trust it for real logins.

### RBAC, audit

`admin_ldap_router` is gated by the existing `require_role("ADMIN")` dependency (`app/core/deps.py`), the same mechanism every other `admin_*` router uses — no parallel permission logic. It is registered only in `_register_admin_routes()` (`app/main.py`), so an `admin`/`user`-listener-mode split deployment (ADR 0011) never exposes it from a user-facing process at all.

Every config write emits `LDAP_CONFIG_CHANGED`; a transition from disabled→enabled or enabled→disabled additionally emits `LDAP_ENABLED`/`LDAP_DISABLED`; every call to `/admin/ldap/test` emits `LDAP_CONNECTION_TESTED` with `{server_uri, success}` — all via the existing `record_security_event()` (`app/services/security_events.py`), the only way this project creates audit rows.

### Group→role mapping, local-role-authority — unchanged by this ADR

`LdapConfig.group_role_mapping` (a `JSONB` dict, `LDAP Group DN -> OpenRBI role name`) becomes admin-portal-editable data, but `resolve_role_from_ldap_groups()`'s exact-string-match semantics (`app/services/ldap_provisioning.py`) and the local-role-authority rule (an account with a real local password keeps its admin-configured role even if it also matches an LDAP identity, ADR 0015) are not touched by B1.8 — only *where the mapping value is read from* changes (DB row instead of `Settings.ldap_group_role_mapping`), not the resolution logic itself.

## Alternatives Considered

- **Generic key/value settings table** for all future admin-configurable settings, not LDAP-specific — rejected: explicitly out of scope per the task, adds indirection (every read needs a key lookup + type coercion) for a configuration surface that has exactly one shape today.
- **Separate draft/pending `LdapConfig` row plus an explicit "activate" endpoint** — rejected in favor of the test-before-enable gate on the single write path (see Decision above): a second table and state machine for a single-row config is more moving parts than the actual safety requirement needs.
- **Merge DB config with env vars field-by-field** (env fills in whatever the DB row leaves blank) — rejected: harder to reason about ("why is this one field still coming from `.env`?"), and the task's own example priority ("persisted admin config → deployment/environment defaults") describes a single fallback step, not a per-field merge.
- **Store the bind password in `.env` only, DB row references it indirectly** — rejected: the task explicitly forbids the running application dynamically rewriting `.env`, and a DB-stored, encrypted secret is the established pattern this project already uses for TOTP secrets.

## Consequences

Adds one new table (`ldap_configs`), one migration for four new `SecurityEventType` enum values, an `app/api/admin_ldap.py` router, and `app/services/ldap_config_service.py`. `/auth/login`'s LDAP branch changes from a cached `settings.ldap_enabled` check to a per-request `get_effective_ldap_config(db)` call — a small, real behavior change (LDAP can now be toggled without a backend restart) that is covered by `backend/tests/integration/test_admin_ldap.py` and the pre-existing `test_ldap_login_flow.py`/`test_ldap_auth.py` suites, both of which pass unmodified in their assertions (only their `LdapAuthProvider` constructor call site changed, not their behavior). Frontend UI (Settings → Authentication → LDAP, group→role mapping table) and the accompanying documentation updates are Roadmap B1.8.3–B1.8.5, tracked separately per the roadmap's own scope discipline.
