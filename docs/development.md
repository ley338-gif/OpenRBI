# Development

## Repository structure

```
OpenRBI/
  backend/            FastAPI control-plane API (auth, users, groups, policies, sessions, incidents, quarantine, audit)
    app/
      api/            HTTP route modules
      core/           config, security primitives (hashing, session tokens, crypto)
      db/             SQLAlchemy engine/session setup
      models/         ORM models
    migrations/       Alembic migrations
  session-agent/       Separate privileged service; only component with sandbox-runtime credentials (see ADR 0004/0005)
  frontend/            npm workspace: two Vite/React/TS SPAs sharing common code
    shared/            Source-only package: API client, auth/MFA flow, UI primitives, design tokens — not independently built
    user/              User Portal (Dashboard, Secure Browser, Downloads, Profile/MFA) — talks to the User listener only
    admin/             Admin Portal (Users, Groups, Sessions, Policies, Quarantine, Incidents, Audit, System) — talks to the Admin listener only
    e2e/               Playwright E2E suite for both portals against the live stack (see "Tests" below)
  docker/              Dockerfiles / configs for nginx, clamav, browser sandbox image, etc.
  docs/                Project documentation (this directory)
  docs/adr/            Architecture Decision Records
  docker-compose.yml   Local/dev orchestration of all services
```

## Build phases

MVP 1 is built in the following order (see the project's master brief §35). Track current status in the session's task list; this table is updated as phases complete.

1. Repository/project foundation — **done**
2. Data model & migrations — **done**
3. Local authentication — **done**
4. TOTP MFA — **done**
5. Roles/groups/authorization — **done**
6. Session Agent — **done** (lifecycle primitives against a placeholder image; the real hardened Firefox/noVNC image lands in Phase 7)
7. Browser sandbox — **done** (Firefox+Xvfb+x11vnc image; remote viewing wiring is Phase 8)
8. noVNC remote browser — **done** (manual test harness; the real session-start flow is Phase 10/11)
9. Network isolation — **done** (`scripts/setup-network-isolation.sh`; see docs/security-model.md for tracked interim gaps: no automatic security event yet, no dedicated DNS-rebinding resolver)
10. Session lifecycle — **done** (real `POST /sessions` orchestration through session-agent; the frontend's "Start Secure Browser" button now drives an actual session, not a manually-typed id)
11. Admin session control — **done** (`/admin/sessions/{id}/{disconnect,isolate,restore,kill}`; Kill restricted to ADMIN only — see docs/security-model.md for the rationale)
12. Policy engine — **done** (draft/publish/rollback, deterministic DENY>QUARANTINE>AUTO_RELEASE conflict model, structural MIME/source matching; wired into the real download/upload pipelines in Phase 13/16)
13. Download interception — **done** (real detection/staging/hashing/magic-byte MIME detection/policy pre-check; every file lands in PENDING_SCAN since no scanner exists yet — see docs/quarantine.md)
14. File scanner — **done** (real ClamAV integration, fail-closed final decision matrix — see docs/quarantine.md#scanning-and-the-final-decision-phase-14)
15. Quarantine — **done** (admin release/reject review, single-use download tokens via Redis GETDEL — see docs/quarantine.md#review-and-release-phase-15)
16. Upload pipeline — **done** (hash/detect/policy/scan/write-to-sandbox via a live exec socket, no async approval queue for uploads — see docs/quarantine.md#upload-pipeline-phase-16)
17. Incidents — **done** (admin management API, repeated-policy-violation aggregation with dedup — see docs/admin-guide.md#incidents-phase-17)
18. Audit/security events — **done** (`GET /admin/security-events`, append-only verified codebase-wide, metadata sensitivity audited — see docs/api.md#audit--security-events-phase-18). Also closed two dead-code gaps found during this pass: group deletion and node drain/undrain, both of which existed only as unused `SecurityEventType` values before now.
19. Health monitoring — **done** (`GET /admin/health`, ADMIN/SECURITY_REVIEWER; checks API, PostgreSQL, Redis, Session Agent, sandbox runtime, browser image availability, ClamAV, and quarantine-storage writability, each independently and non-fatally — see docs/architecture.md#health-monitoring-phase-19)
20. Hardening — **done** (container hardening for every compose service, fail-closed secret validation at startup, per-username login lockout — see docs/security-model.md#control-plane-container-hardening-phase-20)
21. Integration/security tests — **done** (`backend/tests/` pytest suite via `scripts/run-integration-tests.sh`; Docker-socket-dependent checks via `scripts/run-security-tests.sh` — see "Tests" below for what's covered where)
22. Deployment — **done** (TLS overlay `docker-compose.prod.yml` + `docker/nginx/nginx.tls.conf`, `scripts/backup.sh`/`scripts/restore.sh`, full requirements/firewall/storage/update-procedure writeup — see docs/deployment.md)
23. Final documentation review — **done** (architecture.md status table rewritten, user-guide.md written from scratch, admin-guide.md expanded, troubleshooting.md's missing sections added, a real policy-enforcement-scope gap documented in policies.md, DEPENDENCIES.md versions/licenses verified against the actual running stack — including a real finding: `redis:7-alpine` resolves to a post-relicense RSALv2/SSPLv1 version, not BSD-3-Clause)

After each phase: run tests, update documentation, record any known technical debt, and do not silently ignore a known security regression.

## Post-MVP: Productization v0.1.1

The 23 phases above are the original MVP 1 build order and are complete. Work after that point is tracked here rather than renumbered into the phase list, since it's genuinely post-MVP (the DoD walkthrough already passed against the 23-phase result).

- **User/Admin listener separation** — **done**. `docs/analysis/productization-v0.1.1-zone-separation.md` analyzed whether User/Admin plane network segmentation should happen before building the User Portal/Admin Portal UIs and recommended `PREPARE FOR SEGMENTATION, IMPLEMENT LATER`. [ADR 0011](adr/0011-user-admin-listener-separation.md) implements that preparation: `OPENRBI_LISTENER_MODE` (`user`/`admin`/`both`, default `both`) makes `app/main.py`'s router registration conditional, so a `user`-mode process never has an admin route to serve at all (`404`, not `403`). `app/api/mfa.py`'s one admin-only endpoint moved to a new `app/api/admin_mfa.py` (same path, same logic, different router). See [ADR 0012](adr/0012-compact-vs-segmented-deployment.md) for the Compact/Segmented deployment-profile split (`docker-compose.segmented.yml`, illustrative and tested, not yet a complete production guide) and [ADR 0013](adr/0013-browser-isolation-zone.md) for why no new Browser Isolation Zone was built (it already exists as `browser-plane`). No business logic, session lifecycle, browser sandbox, noVNC, file pipeline, quarantine, or audit code changed — see `docs/security-model.md#useradmin-listener-separation-productization-v011` for exactly what this does and does not mitigate.
- **User Portal / Admin Portal UI** — **done**. Two Vite/React/TypeScript SPAs (`frontend/user/`, `frontend/admin/`) sharing `frontend/shared/` via an npm workspace — see [ADR 0014](adr/0014-separate-user-and-admin-portal-frontends.md) and [architecture.md#user-portal-and-admin-portal-productization-v011](architecture.md#user-portal-and-admin-portal-productization-v011). Built and verified end-to-end against the live stack (real login/MFA, a real noVNC-connected Secure Browser session, real downloads/uploads for the User Portal; real user/session/policy/quarantine/incident management for the Admin Portal) — no mocked data anywhere in either app. Two genuine bugs surfaced only by this live-browser testing are documented in [ADR 0014](adr/0014-separate-user-and-admin-portal-frontends.md)'s Consequences and [troubleshooting.md](troubleshooting.md): a React ref-timing race in the noVNC connect sequence (fixed), and a session-status write race between `terminate_session` and the display WebSocket's own close handler (a pre-existing backend concurrency issue, documented as a known limitation, not fixed in this pass).

### Frontend development

```bash
cd frontend
npm install                       # hoists shared deps for frontend/shared/ via the workspace root

npm run dev --workspace=user      # http://localhost:5173, proxies /api to the backend — see frontend/user/vite.config.ts
npm run dev --workspace=admin     # http://localhost:5174

npm run build --workspace=user    # frontend/user/dist
npm run build --workspace=admin   # frontend/admin/dist
```

Both apps read their API base URL from `VITE_API_BASE_URL` (`.env`/`.env.example` in each app's directory) at build time — see [deployment.md#user-portal-and-admin-portal-origins](deployment.md#user-portal-and-admin-portal-origins) for Compact vs. Segmented values. `frontend/shared/` has no build step of its own; both apps' own Vite config aliases `@shared` to it directly and compile its `.tsx`/`.ts` files as part of their own build.

## CI

Roadmap Phase A / A5, `.github/workflows/ci.yml` — until this landed, every check below only ran when someone remembered to run it by hand. Three jobs, all on `push` to `main` and every pull request:

- **`image-scan`** — builds `openrbi-backend`, `openrbi-session-agent`, `openrbi-frontend`, and `openrbi-browser` and scans each with Trivy for CRITICAL vulnerabilities, failing the build on anything not explicitly listed in `.trivyignore` (every entry there is a CVE individually verified to have no upstream fix yet — see that file's header for how and when it was checked, and re-verify before trusting it as still accurate).
- **`dependency-scan-frontend`** — `npm audit --audit-level=critical` against the frontend workspace. The only place npm-level CVEs are actually checked, since the final frontend image is a static nginx build that never ships `node_modules`.
- **`backend-integration-tests`** — brings up the full `docker compose` stack (with freshly generated random secrets, not `.env.example`'s placeholders, which the Phase 20 fail-closed startup check would reject anyway) and runs `scripts/run-integration-tests.sh` and `scripts/run-security-tests.sh` — the same two suites described below, now actually gating merges instead of only running when someone remembered to.

## Tests

Unit tests alone are not sufficient. Phase 21's checklist (project brief §30, non-exhaustive) is covered across two runners, split by what each one can actually reach:

**`backend/tests/` (pytest, via `scripts/run-integration-tests.sh`)** — runs inside the backend container against the real Postgres/Redis/Session Agent, never mocks. Covers: a disabled user cannot log in (identically to a wrong password — no distinct error that would leak account state); admin/security-reviewer login requires MFA enrollment before any session is issued; recovery codes are single-use; MFA reset disables MFA, wipes recovery codes, and generates `MFA_RESET`; the per-username login lockout (Phase 20) actually blocks the *correct* password once tripped, and generates `LOGIN_LOCKED`; user A cannot see or act on user B's session or quarantine file (404, not 403), and this holds for an ADMIN account too — no implicit ownership; a download token is bound to the user it was issued to; MIME `DENY` rules block; an unmatched file type fails closed to `QUARANTINE`; forged-domain source rules (`microsoft.com.attacker.org`, `evil-microsoft.com`) never match `*.microsoft.com`; conflicting group policies resolve to the most restrictive action; publish/rollback generate `POLICY_PUBLISHED`/`POLICY_CHANGED`; release tokens are single-use (a second `consume_token` on the same token fails) and expire; admin disconnect/isolate/restore/kill all work against a real sandbox via the real Session Agent, are audited (`SESSION_ISOLATED`/`SESSION_TERMINATED`), and kill is correctly ADMIN-only (403 for SECURITY_REVIEWER).

**`scripts/run-security-tests.sh`** — the handful of checks that need the Docker socket or the ability to stop other containers, neither of which the backend has by design (ADR 0005), so these run from the host instead: sandbox network isolation (public internet reachable; Postgres's real IP, the cloud metadata address, and an arbitrary RFC1918 address all unreachable from `browser-plane`); an admin Isolate leaves the real sandbox container with zero Docker networks attached — the actual DENY-ALL primitive, not just a database flag; a scanner outage (ClamAV container actually stopped) is detected as an error rather than a silent clean result, which is the precondition `app/services/scanning.py`'s fail-closed decision matrix depends on. Roadmap Phase A / A3 added two more, closing gaps `docs/security-self-assessment.md` found: a real sandbox's VNC port is unreachable from anything else on `browser-plane` (sandbox-to-sandbox isolation, previously only checked once by hand in Phase 9); and a hostname whose DNS answer is faked to point at a blocked address is still blocked (DNS-rebinding), proving the egress rule keys on the resolved IP, not the requesting hostname. As of A5, this script and `run-integration-tests.sh` both run automatically in CI (`.github/workflows/ci.yml`) on every push/PR — previously both were only ever run by hand.

Both are meant to run against an already-running `docker compose up` stack, not a separate test-only environment — see each script's own header comment for details (test data is prefixed `pytest_` and swept up automatically; the security-tests script briefly stops ClamAV and a throwaway sandbox container, restoring/removing them itself).

**`scripts/run-ldap-tests.sh`** (Roadmap Phase B / B1.2/B1.6) — `LdapAuthProvider` tested directly (no HTTP, no `/auth/login`) against a real, throwaway `osixia/openldap` server with a real self-signed certificate and real StartTLS: correct/wrong/unknown credentials, empty-password/anonymous-bind rejection, LDAP filter-injection, unreachable-server fail-closed, and `health()`.

**`scripts/run-ldap-integration-tests.sh`** (Roadmap Phase B / B1.4-B1.6, extended by B1.8.5) — the HTTP-level complement: actually restarts `backend` with `OPENRBI_LDAP_*` pointed at a throwaway LDAPS server (the running `uvicorn` process only reads `Settings()` once, so there's no way to flip this per-request), then drives real `POST /auth/login` requests. Covers: a login mapped via LDAP group to `ADMIN` gets the same mandatory-MFA-enrollment flow a local admin would (reuses `tests/conftest.py`'s existing `login_with_mfa_enrollment` helper unchanged, and confirms the resulting session's role and the `USER_PROVISIONED_VIA_LDAP` audit event); local accounts still log in normally with LDAP enabled; a failed LDAP bind counts toward the exact same per-username lockout counter a failed local attempt would; a config saved via the admin API's DB-persisted group→role mapping is the one actually used by a real login, not the env var (`test_admin_editable_group_role_mapping_is_used_at_real_login` — the regression test for a real bug this same B1.8.5 pass found and fixed); and — with the LDAP container genuinely stopped by the host script, since the backend has no Docker socket access to do this itself (ADR 0005), the same boundary `run-security-tests.sh`'s ClamAV-outage test respects — an unreachable LDAP server denies login rather than falling back to anything. `.env` is temporarily modified and always restored via a trap, the same "leave the stack exactly as it was" discipline `run-security-tests.sh` applies to ClamAV. Also runs `backend/tests/integration/test_admin_ldap.py` — the admin LDAP configuration HTTP API (`GET/PUT /admin/ldap/config`, `POST /admin/ldap/test`) against this same restarted backend, needed specifically because that API's TLS handshake happens inside the `uvicorn` process itself (unlike `run-ldap-tests.sh`, which talks to `LdapAuthProvider` in-process within pytest) — RBAC, secret handling (never returned, empty-on-update keeps the existing one, explicit value replaces it), the stateless test endpoint never persisting anything, and a rejected enable-with-broken-config leaving the previously saved config untouched.

**`scripts/verify-fresh-install.sh`** (Roadmap Phase B / B1.9) — proves the actual Definition of Done claim, not just `backend/tests/integration/test_setup.py`'s pytest-level coverage: spins up a genuinely empty, throwaway Postgres (its own container/volume, never the shared dev `postgres-data` volume), runs `alembic upgrade head` against it from nothing, starts a fresh backend pointed at it, then drives `GET /setup/status` → `POST /setup/admin` (using the setup token read from that backend's own console log, exactly as an operator would, never from the database) → the existing `POST /mfa/setup/enroll` → `POST /setup/mfa/confirm` over real HTTP. Restarts the backend afterward and confirms `setup_required` stays `false`, no new setup token is logged, and a normal `/auth/login` for the bootstrap admin still works. Cleans up its own throwaway containers on exit (even on failure) and never touches the real dev stack.

**`scripts/test-listener-modes.sh`** (Productization v0.1.1) — verifies `OPENRBI_LISTENER_MODE` actually changes which routes exist, run from the host for the same reason as `run-security-tests.sh` (needs Docker access to start throwaway sibling containers with different env vars): in `user` mode every admin route is a `404` and the OpenAPI schema contains no `/admin` paths; in `admin` mode every admin route exists (`401`, not `404`) and user-only routes are `404` with no leak in the OpenAPI schema; `both` mode is unchanged from prior behavior; an invalid `OPENRBI_LISTENER_MODE` value fails container startup immediately with a clear error.

**`scripts/e2e-run.sh`** (Productization v0.1.1) — a real, no-mock Playwright suite (`frontend/e2e/`) driving both portals through an actual Chromium browser against the already-running Compact stack: seeds `e2e_admin` (pre-enrolled with a known TOTP secret), `e2e_admin_enroll` (deliberately unenrolled, for the one test that exercises the real first-login mandatory-MFA-enrollment UI flow end to end), and `e2e_user` via the real `create_user()` service function, then always tears them down again (even on failure). Covers: wrong-credentials shows a generic message (never raw JSON/a traceback); a real Secure Browser session reaching a genuine noVNC-connected canvas and a clean End Session; logout clearing the session so a fresh navigation is redirected back to `/login`; the Admin Portal's mandatory-MFA-enrollment flow showing recovery codes *before* the dashboard, not skipped past it (the exact regression documented in `frontend/shared/auth/LoginFlow.tsx`'s comments); real Users/System/Quarantine pages rendering actual backend data with no fake preview; and a UI-level listener-boundary check that the User Portal's own session gets `403`/`404`, never `200`, calling the admin API directly. Building this suite surfaced and fixed two real frontend bugs neither manual testing nor the unit-level work had caught: `FormField`'s `<label>` was never actually associated with its input (no `htmlFor`, not wrapping it) — a real accessibility defect independent of testing, not just a test-tooling inconvenience — and the MFA-enrollment `refresh()` call (itself a fix from earlier manual testing) was placed *before* the recovery-codes screen rendered, which under React's update batching skips that screen entirely because the `/login` route swaps to a redirect the instant `user` becomes truthy. Both are fixed in `frontend/shared/components/FormField.tsx` and `frontend/shared/auth/LoginFlow.tsx` respectively.

## Migrations

Backend uses Alembic. Every schema change ships as a migration — no manual schema edits against a running database.

## Developing a new provider

To add a new `SandboxProvider`/`DisplayProvider`/`BrowserProvider`/`FileScanner` implementation: implement the relevant interface (see [architecture.md](architecture.md#provider-architecture)), register it via configuration, and add it to [DEPENDENCIES.md](../DEPENDENCIES.md). Core session/policy code must not import the concrete provider's SDK directly.

## Coding standards

Services and clearly defined interfaces over God classes; business logic stays out of UI components and controllers; no direct container-runtime calls from the backend (see [ADR 0005](adr/0005-no-docker-socket-in-backend.md)); centralized authorization and policy evaluation (no duplicated permission checks); typed events, not magic strings; schema-validated inputs; migrations for all schema changes; linting and automated tests are part of "done," not optional cleanup.
