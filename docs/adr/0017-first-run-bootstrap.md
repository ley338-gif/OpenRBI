# ADR 0017: First-run bootstrap of the initial local administrator

## Status

Accepted

## Context

Before Roadmap B1.9, there was no way to create the first OpenRBI administrator without direct database access — `docs/deployment.md`'s installation walkthrough ended at "the stack is reachable on `http://<host>:8080`" with no next step, and every existing account-creation path (`POST /admin/users`, LDAP JIT-provisioning) itself requires an already-authenticated `ADMIN`. A fresh installation is a chicken-and-egg problem this project had never actually closed.

The obvious naive check, "no users exist yet" (`COUNT(users) == 0`), is explicitly rejected: it would let an administrator who later deletes every user account (accidentally, or as an attack) silently reopen an unauthenticated, world-reachable "create an ADMIN" endpoint — a privilege-escalation path, not a recovery mechanism.

## Decision

### Persisted, one-way initialization flag — not derived from user count

A new single-row table, `system_state` (`app/models/system_state.py`), same pattern as B1.8's `ldap_configs`: a fixed, well-known UUID primary key guarantees at most one row. Its `initialized: bool` starts `False` and is set to `True` exactly once, by `complete_bootstrap_mfa` — never re-derived from any other table's contents, and nothing in the application ever sets it back to `False`. `GET /setup/status` reports `{"setup_required": not initialized}` and nothing else — no username, no LDAP state, no internal configuration.

### Reuse, not a second user/password/MFA implementation

`app/services/setup_service.py` calls straight into the existing mechanisms, unmodified:
- `app/services/users.py`'s `create_user()` for the account itself — the same Argon2 hashing, the same (currently nonexistent) password policy every other admin-created account gets, no bootstrap-specific password rule.
- `app/core/sessions.py`'s `create_mfa_pending()`/`get_mfa_pending()` for the pending-MFA-challenge token — the bootstrap admin walks through the *existing*, unmodified `POST /mfa/setup/enroll` and gets its QR code exactly the way any other newly-created `ADMIN`'s first login does.
- `app/services/mfa.py`'s `confirm_enrollment()` for TOTP verification and recovery-code issuance — called directly, not re-implemented.
- `app/core/sessions.py`'s `create_session()` for the real session issued once setup completes.
- `app/core/sessions.py`'s `is_login_locked`/`record_login_failure`/`clear_login_failures` for setup-token brute-force protection, keyed by a fixed pseudo-username (`__setup_bootstrap__`) instead of a second rate-limiting mechanism.

Only one new HTTP-facing behavior exists that isn't a thin wrapper: `POST /setup/mfa/confirm` additionally flips `system_state.initialized = True` in the same transaction as the TOTP verification — deliberately a separate endpoint from the shared `/mfa/setup/confirm` (used by every other mandatory-MFA-enrollment login), rather than adding bootstrap-specific branching to a shared, heavily-tested endpoint.

### Console-only setup token (Section 9)

A freshly exposed, uninitialized instance is reachable by anyone who can reach the server at all — `GET /setup/status` and `POST /setup/admin` are necessarily unauthenticated. To close the "whoever gets there first becomes admin" race on a network-reachable fresh install, `POST /setup/admin` additionally requires a cryptographically random token (`secrets.token_urlsafe(24)`), generated fresh on every backend startup while `initialized` is still `False` and printed once to the process's own log — never returned by any API, never repeated per-request. Only its Argon2 hash and issuance time are persisted. The token expires after 30 minutes by default (`OPENRBI_SETUP_TOKEN_TTL_SECONDS`) and a container restart before setup completes issues a fresh token, implicitly invalidating any unused previous one. A lost or expired token is therefore recoverable by restarting, never by database access. The token becomes permanently unusable the instant `initialized` flips to `True` (`complete_bootstrap_mfa` clears the stored hash and timestamp), and it is checked nowhere except `POST /setup/admin` — never reusable as a session or MFA token, never touching either of those Redis-backed stores.

### Race-condition safety: row-locking, not "check then act"

Both `create_bootstrap_admin` and `complete_bootstrap_mfa` take out `SELECT ... FOR UPDATE` on the single `system_state` row before reading or changing anything. A second, concurrent request blocks until the first transaction commits, then observes up-to-date state — already initialized, or the same in-progress bootstrap account — and can never create a second administrator or double-initialize the system. A retried `POST /setup/admin` (e.g. after a browser crash mid-setup, before MFA enrollment completed) reuses the same account via `system_state.setup_admin_user_id` rather than creating a second one.

### Placement: admin-capable listener only, deliberately unauthenticated

`setup_router` is registered in `_register_admin_routes()` (`app/main.py`) — reachable only from an admin-capable listener (ADR 0011), matching where the Admin Portal itself lives — but is **not** gated by `require_role`, since by definition no authenticated actor exists yet. It is closed by three independent layers instead: the persisted `initialized` flag (`409` once true), the console-only setup token, and the shared rate-limiting mechanism — not by RBAC, which has nothing to check against here.

### Audit with a system actor

`INITIAL_ADMIN_CREATED` fires when the bootstrap account is created (safe metadata: username only, never the password or setup token); `SYSTEM_INITIALIZED` fires once, in the same transaction as the completing MFA confirmation. Both use the bootstrap-created user's own id as the event's `user_id` (there is no other actor to attribute it to yet) — `created_by` on the underlying `create_user()` call is a fixed sentinel UUID (`BOOTSTRAP_SYSTEM_ACTOR_ID`), stored only as metadata text, never a foreign key, matching how the rest of the audit model already treats `created_by`/`actor`/`reset_by` fields.

## Alternatives Considered

- **`COUNT(users) == 0` as the initialization check** — rejected as described in Context: a real privilege-escalation path if every user is later deleted.
- **A CLI/one-off script (`python manage.py createsuperuser`-style) instead of an HTTP flow** — rejected: the task's explicit goal is a browser-only path with *no* manual database or exec access required at all; a CLI script still requires shell access to the container, which is exactly the class of step this ADR removes.
- **No setup token at all, relying only on network/deployment controls** — considered and explicitly available as a lighter option, but rejected after review: a fresh install reachable over a real network before an operator has firewalled it is a real, not hypothetical, exposure window, and the token costs little (one extra field on one form) for a meaningful reduction in that window.
- **A single combined `POST /setup/admin` that also takes the TOTP code inline (no separate MFA step)** — rejected: this would either weaken MFA enrollment (accepting a code before the QR/secret has ever been shown to the operator) or force the frontend to fabricate its own enrollment UI instead of reusing the existing, already-tested one.

## Consequences

Adds one table (`system_state`), two new `SecurityEventType` values, `app/services/setup_service.py`, `app/api/setup.py`, and a small FastAPI `lifespan` hook in `app/main.py` for token generation/logging. `/auth/login`, `/mfa/*`, and every existing account-management endpoint are completely unmodified — verified by the full pre-existing integration suite passing unchanged alongside the new `backend/tests/integration/test_setup.py`. The Admin Portal's first-run UI, the fresh-install end-to-end verification, and the remaining documentation updates are Roadmap B1.9's later sub-steps, tracked separately per the roadmap's own scope discipline.
