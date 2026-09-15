# ADR 0025: Per-listener Postgres roles and Session Agent token scopes for Segmented deployment

## Status

Accepted

## Context

[ADR 0011](0011-user-admin-listener-separation.md) gave `backend-user`/`backend-admin`
(Segmented deployment, [ADR 0012](0012-compact-vs-segmented-deployment.md)) a real
route-existence boundary: in `user` mode, admin routers are never registered, so a request to
`/admin/*` is a `404`, not a `403`. That ADR's own "Alternatives Considered" section explicitly
deferred the next layer — "Separate Postgres roles / Session Agent token scopes per listener" —
as a follow-up, not blocking that phase. `docs/security-self-assessment.md`'s V4 Access Control
GAP row and `docs/deployment.md`'s Segmented section (both cross-referencing each other) have
carried this forward ever since as a documented, not-yet-implemented item.

The residual risk this leaves: `backend-user` and `backend-admin` are two OS processes, but they
still authenticate to Postgres as the same role and to the Session Agent with the same static
bearer token. A route not existing in a process stops a well-behaved caller from reaching it
through FastAPI's routing — it does nothing against a **code-execution-level compromise** of that
process (a dependency RCE, a deserialization bug, a SQL-injection primitive). Once an attacker is
executing arbitrary code or arbitrary SQL inside `backend-user`, FastAPI's router is irrelevant:
they hold that process's actual Postgres and Session Agent credentials directly, and today those
credentials are identical to `backend-admin`'s. Concretely, that compromise today can: read any
user's encrypted TOTP secret and the LDAP bind password, read or edit policy definitions, and call
the Session Agent's `isolate`/`restore` endpoints or list every sandbox on the node directly — all
actions RBAC in `backend-admin`'s own Python code would otherwise gate, but RBAC never runs inside
the database or the Session Agent, only inside the FastAPI process itself.

**Table access is not a clean user/admin partition.** `app/api/auth.py` and `app/api/mfa.py` are
*shared* routes (registered in every listener mode, per `app/main.py`'s `_register_shared_routes`)
because every login and every MFA enrollment — regardless of which portal or listener served it —
needs the `users` and `roles` tables. `browser_nodes` is read by user-registered `display.py` (to
resolve which node's Session Agent to relay to) and written by admin-registered `admin_nodes.py`/
`node_enrollment.py`. `security_events` is written by shared auth/MFA code and read by admin's
audit views. Any role split has to accept this overlap rather than pretend the tables partition
cleanly along listener-mode lines.

## Decision

Two independent, additive credential-scoping mechanisms, both **opt-in and Segmented-only** —
Compact (`OPENRBI_LISTENER_MODE=both`, the only deployment style with a complete production guide)
requires zero configuration changes and is byte-for-byte unaffected.

### 1. Postgres: `openrbi_user` and `openrbi_admin` roles

A new `scripts/provision-segmented-db-roles.sh`, run by hand, once, **after** `alembic upgrade head`
— not a `docker-entrypoint-initdb.d` script. That was the first design tried here and it doesn't
work: `initdb.d` scripts run at Postgres's very first boot, before any migration has ever created a
single table, so every `GRANT ... ON <table>` in it fails outright with `relation does not exist`
(caught by actually running it against a throwaway container during this work, not assumed). The
script is idempotent — safe to re-run after a version upgrade adds new admin-only tables, or to
rotate the two role passwords — and connects as the existing `POSTGRES_USER` superuser/owner role,
the same role migrations themselves already run as, never as either new role itself. Neither
Compact's `docker-compose.yml` nor `docker-compose.segmented.yml` reference it or require anything
new; it's purely an additional operator step, matching how this project already documents running
migrations themselves (`docs/deployment.md`'s Quick Start: `alembic upgrade head` — required on a
fresh database, not automatic either). The `backend-user`/`backend-admin` side of this feature
needs no compose changes at all — both services already load the whole `.env` via `env_file`, so
the four new backend-side variables (§3 below) just need to be set there, once the roles exist.

- **`openrbi_admin`**: the same effective privileges the single `openrbi` role has today
  (SELECT/INSERT/UPDATE across every application table). No behavior change for `backend-admin` —
  it is already the intentionally-trusted control-plane role, and Segmented's admin process is
  meant to retain full application-data access, matching Compact's single role. No blanket
  `DELETE` grant, consistent with the append-only audit-log invariant
  `docs/security-self-assessment.md`'s V7 section already relies on elsewhere.
- **`openrbi_user`**: SELECT/INSERT/UPDATE on `browser_sessions` and `quarantine_files` only (the
  tables user-registered routes — `sessions.py`, `files.py`, `display.py` — actually own); SELECT
  on `users`, `roles`, `browser_nodes` (needed by the shared auth/MFA path and by `display.py`'s
  node-connection resolution — full-row `SELECT` is unavoidable here since login must read a
  candidate row, including its password/TOTP columns, before it knows whether the caller is who
  they claim); INSERT-only on `security_events` (write the audit trail, never read or rewrite it);
  column-level `UPDATE` on `users` restricted to exactly `password_hash`, `mfa_enabled`,
  `totp_secret_encrypted`, `updated_at` — the genuine self-service writes shared `auth.py`/`mfa.py`
  make on the *authenticated caller's own row* (change-my-password, enroll-my-own-MFA); **no**
  `INSERT` on `users` at all, and **no** `UPDATE` on `role_id`/`is_active`/`disabled_at`, so this
  role cannot create a new account or rewrite any account's privilege level even via a raw
  SQL-injection primitive; **no grant at all** on `groups`, `user_groups`, `policies`,
  `policy_versions`, `group_policies`, `ldap_configs`, `incidents`, or `worker_metric_samples`, and
  no write access to `browser_nodes` (`agent_token_encrypted` and the rest of that table's
  management columns stay admin-only).

This makes the boundary real at the database engine level — a `backend-user` compromise attempting
to read `ldap_configs` or write `users.role_id` gets Postgres's own permission-denied error, not
just an absent application code path.

**Interaction with LDAP auto-provisioning, made an explicit incompatibility rather than a silent
break**: `app/services/ldap_provisioning.py`'s `resolve_or_provision_ldap_user()` — called from the
*shared* `/auth/login` route, so it runs inside whichever listener process serves a given login —
creates a brand-new local `User` row (`INSERT`, with `role_id` required and NOT NULL) on a
directory identity's first successful bind, and rewrites `role_id` on every subsequent login if the
user's current LDAP groups now map to a different role. Both are exactly the writes `openrbi_user`
above is deliberately denied, for exactly the reason this ADR exists (a compromised process must
not be able to set its own privilege level). There is no way to keep this legitimate feature
working through a role-scoped `user`-mode process without either reopening `role_id`/`INSERT` on
`users` (which would gut the property this ADR delivers) or restructuring the login transaction
to route only that one write through an elevated connection while keeping the rest of the same
request's DB work (session-cookie issuance, `USER_LOGIN`/`LOGIN_LOCKED` audit events, the
flush-but-don't-commit-until-MFA-completes sequencing `auth.py` already relies on) on the
caller's own connection — a materially larger, transaction-semantics-changing effort not justified
by this ADR's scope. Instead: **fail closed at startup.** A new `Settings` validator refuses to
start a `listener_mode="user"` process that has both `database_url_user` set (role scoping opted
in) and `ldap_enabled=True` — an operator who wants both DB role scoping *and* LDAP auto-provisioning
for the user-facing process must run that process in `both` mode instead (keeping LDAP login on the
single, fully-privileged role), or provision/maintain LDAP-mapped accounts' roles only through
`backend-admin`. `backend-admin` is unaffected either way, since it always holds full
`openrbi_admin` privileges.

### 2. Session Agent: per-route token scopes

`session-agent/app/config.py` gains `api_token_user`/`api_token_admin` alongside the existing
`api_token` (kept as a legacy full-access credential so Compact and any Segmented deployment that
hasn't adopted scoping yet are unaffected). `session-agent/app/auth.py`'s
`require_control_plane_token` becomes a dependency factory parameterized by
`required_scope: Literal["user", "admin"]`; every configured candidate token is checked with
`hmac.compare_digest` unconditionally (all comparisons always run, never short-circuited) to avoid
a timing side-channel between "matches the admin token" and "matches the user token". `api_token`
and `api_token_admin` both satisfy either required scope — admin is a superset, because
admin/both-mode-only background work (orphan reconciliation) also calls `terminate_sandbox`.
`api_token_user` satisfies only `"user"`.

Route scope assignment in `session-agent/app/api/sandboxes.py` and `main.py`:

| Scope | Routes |
|---|---|
| `admin` | `GET /v1/sandboxes` (list every sandbox on the node), `POST /{id}/isolate`, `POST /{id}/restore` |
| `user` | create, start, terminate, status, display info, display-ready, the display WebSocket, downloads (list/fetch/delete), uploads, metrics, `GET /v1/nodes/self` |

`isolate`/`restore` are genuinely incident-response-only actions (never called by a user acting on
their own session); listing every sandbox on a node discloses other users' active session IDs and
is reconciliation/admin-dashboard-only. `GET /v1/nodes/self` is **not** admin-only despite reporting
host-wide telemetry: `app/services/sessions.py`'s `select_node()` calls it synchronously as part of
real-time session scheduling — user-registered code, so it must stay reachable from a `user`-scope
token, or session creation itself would break under scoping. The node poller's own admin/both-mode
background polling of the same endpoint still works, since the admin/legacy token is a strict
superset. `terminate` stays in the `user` scope because ending one's own session is a normal user
action (and admin's own Kill action already works via
the superset `admin` scope).

### 3. Backend wiring

`backend/app/config.py` adds four new optional, empty-string-default settings —
`database_url_user`, `database_url_admin`, `session_agent_api_token_user`,
`session_agent_api_token_admin` — with no new validator forcing them. `backend/app/db/session.py`
resolves which database URL to build its single module-level engine from: `database_url_user`/
`database_url_admin` when `listener_mode` is `"user"`/`"admin"` and that setting is non-empty,
else the existing `database_url` unchanged (`both` mode always uses the shared URL — splitting
credentials for one process that already holds every role is meaningless).
`backend/app/services/nodes.py`'s `connection_for_node()` gets the same resolution shape for the
Session Agent token it falls back to when a `BrowserNode` has no per-node token configured.

## Alternatives Considered

- **Row-level security (Postgres `RLS` policies) instead of role-level table/column grants** —
  would allow one shared role with per-request-context row filtering. Rejected: OpenRBI's
  connection pooling doesn't set a per-request Postgres session variable today, and introducing
  one purely for this would add a new, easy-to-get-wrong trust dependency (an app-set session
  variable, not a connection-level credential) for a boundary that plain per-role `GRANT`s already
  deliver without any new mechanism.
- **A full second Postgres database/schema per listener** — would give the cleanest possible
  isolation but contradicts the overlap finding above: shared auth code genuinely needs to read
  `users`/`roles` from *both* listener processes, so a hard schema split would require either
  duplicating those tables (a replication/consistency problem) or a cross-schema view (no cleaner
  than a role-level grant, with more moving parts). Rejected for this project's stated
  homelab/KMU-first scope.
- **Session Agent token scopes as a bitmask/claims token (e.g., signed JWT) instead of two static
  shared secrets** — more flexible for a future with more than two scopes, but the Session Agent
  has no existing token-issuance flow (its one credential today is a static shared secret set via
  environment, same pattern the per-node tokens in Roadmap B2.1 also use) — adding a signing/issuing
  mechanism for exactly two fixed scopes is unjustified complexity. Rejected; revisit if a third
  scope is ever needed.
- **Do nothing further, rely on route non-existence alone** — the status quo since ADR 0011.
  Rejected because it leaves the process-compromise threat this ADR addresses completely open, and
  the gap has already been carried as a known, cross-referenced open item for multiple releases.
- **A second, always-admin-privileged DB session used only inside `resolve_or_provision_ldap_user()`**,
  so `openrbi_user` could keep its `role_id`/`INSERT` restriction while LDAP auto-provisioning kept
  working transparently through `backend-user`. Rejected for this pass: `auth.py`'s login flow
  deliberately keeps the JIT-provisioned row and its audit event un-committed (`flush()` only) until
  the MFA/role-mandatory branches below it decide the request's outcome, so the provisioning write
  and the rest of the request's DB work must stay in one transaction/connection — splitting them
  across two roles changes that commit semantics and would need its own careful review against
  `test_ldap_login_flow.py`'s existing coverage. The fail-closed startup check below is smaller,
  safer, and doesn't touch a security-sensitive, already-tested transaction boundary; revisit the
  dual-session approach as a follow-up if the LDAP+scoping combination turns out to be commonly
  wanted together.

## Consequences

- Segmented deployment's credential boundary is now real for operators who opt in: a
  `backend-user` compromise cannot read `ldap_configs`/policy tables/other users' node-management
  data at the database level, and cannot call `isolate`/`restore`/list-all-sandboxes against the
  Session Agent directly, regardless of what its own RBAC code would have said.
- A `listener_mode="user"` process refuses to start if `database_url_user` (role scoping) and
  `ldap_enabled` are both set — a deliberate, documented incompatibility (see above), not a
  runtime surprise the first time an LDAP user tries to log in through it.
- This closes the *credential* boundary only, not a network boundary — `backend-user` and
  `backend-admin` still share the same `control-plane` Docker network and can still reach Postgres,
  Redis, and the Session Agent's address directly; genuine network segmentation between the two
  listener processes remains out of scope, consistent with Segmented's existing
  "experimental/technology preview" positioning.
- Adopting this needs one manual, operator-run step (`scripts/provision-segmented-db-roles.sh`,
  after `alembic upgrade head`) for both a new and an existing Segmented deployment alike — it is
  never automatic, by design (see §1 above). Compact deployments need no action at all; the new
  settings default to empty and are ignored.
- `docs/deployment.md`, `docs/security-self-assessment.md` (the V4 GAP row), and
  `docs/architecture.md`'s listener-mode section are updated alongside this decision to describe
  what's now implemented, replacing their "documented, not implemented" language.
