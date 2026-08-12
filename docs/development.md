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
  frontend/            React + TypeScript + Vite SPA (admin + user portals)
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
12. Policy engine — **done** (draft/publish/rollback, deterministic DENY>QUARANTINE>AUTO_RELEASE conflict model, structural MIME/source matching; not yet wired into a real download/upload pipeline — that's Phase 13+)
13. Download interception — **done** (real detection/staging/hashing/magic-byte MIME detection/policy pre-check; every file lands in PENDING_SCAN since no scanner exists yet — see docs/quarantine.md)
14. File scanner — **done** (real ClamAV integration, fail-closed final decision matrix — see docs/quarantine.md#scanning-and-the-final-decision-phase-14)
15. Quarantine — **done** (admin release/reject review, single-use download tokens via Redis GETDEL — see docs/quarantine.md#review-and-release-phase-15)
16. Upload pipeline — **done** (hash/detect/policy/scan/write-to-sandbox via a live exec socket, no async approval queue for uploads — see docs/quarantine.md#upload-pipeline-phase-16)
17. Incidents — **done** (admin management API, repeated-policy-violation aggregation with dedup — see docs/admin-guide.md#incidents-phase-17)
18. Audit/security events — **done** (`GET /admin/security-events`, append-only verified codebase-wide, metadata sensitivity audited — see docs/api.md#audit--security-events-phase-18). Also closed two dead-code gaps found during this pass: group deletion and node drain/undrain, both of which existed only as unused `SecurityEventType` values before now.
19. Health monitoring — **done** (`GET /admin/health`, ADMIN/SECURITY_REVIEWER; checks API, PostgreSQL, Redis, Session Agent, sandbox runtime, browser image availability, ClamAV, and quarantine-storage writability, each independently and non-fatally — see docs/architecture.md#health-monitoring-phase-19)
20. Hardening — **done** (container hardening for every compose service, fail-closed secret validation at startup, per-username login lockout — see docs/security-model.md#control-plane-container-hardening-phase-20)
21. Integration/security tests — **done** (`backend/tests/` pytest suite via `scripts/run-integration-tests.sh`; Docker-socket-dependent checks via `scripts/run-security-tests.sh` — see "Tests" below for what's covered where)
22. Deployment
23. Final documentation review

After each phase: run tests, update documentation, record any known technical debt, and do not silently ignore a known security regression.

## Tests

Unit tests alone are not sufficient. Phase 21's checklist (project brief §30, non-exhaustive) is covered across two runners, split by what each one can actually reach:

**`backend/tests/` (pytest, via `scripts/run-integration-tests.sh`)** — runs inside the backend container against the real Postgres/Redis/Session Agent, never mocks. Covers: a disabled user cannot log in (identically to a wrong password — no distinct error that would leak account state); admin/security-reviewer login requires MFA enrollment before any session is issued; recovery codes are single-use; MFA reset disables MFA, wipes recovery codes, and generates `MFA_RESET`; the per-username login lockout (Phase 20) actually blocks the *correct* password once tripped, and generates `LOGIN_LOCKED`; user A cannot see or act on user B's session or quarantine file (404, not 403), and this holds for an ADMIN account too — no implicit ownership; a download token is bound to the user it was issued to; MIME `DENY` rules block; an unmatched file type fails closed to `QUARANTINE`; forged-domain source rules (`microsoft.com.attacker.org`, `evil-microsoft.com`) never match `*.microsoft.com`; conflicting group policies resolve to the most restrictive action; publish/rollback generate `POLICY_PUBLISHED`/`POLICY_CHANGED`; release tokens are single-use (a second `consume_token` on the same token fails) and expire; admin disconnect/isolate/restore/kill all work against a real sandbox via the real Session Agent, are audited (`SESSION_ISOLATED`/`SESSION_TERMINATED`), and kill is correctly ADMIN-only (403 for SECURITY_REVIEWER).

**`scripts/run-security-tests.sh`** — the handful of checks that need the Docker socket or the ability to stop other containers, neither of which the backend has by design (ADR 0005), so these run from the host instead: sandbox network isolation (public internet reachable; Postgres's real IP, the cloud metadata address, and an arbitrary RFC1918 address all unreachable from `browser-plane`); an admin Isolate leaves the real sandbox container with zero Docker networks attached — the actual DENY-ALL primitive, not just a database flag; a scanner outage (ClamAV container actually stopped) is detected as an error rather than a silent clean result, which is the precondition `app/services/scanning.py`'s fail-closed decision matrix depends on.

Both are meant to run against an already-running `docker compose up` stack, not a separate test-only environment — see each script's own header comment for details (test data is prefixed `pytest_` and swept up automatically; the security-tests script briefly stops ClamAV and a throwaway sandbox container, restoring/removing them itself).

## Migrations

Backend uses Alembic. Every schema change ships as a migration — no manual schema edits against a running database.

## Developing a new provider

To add a new `SandboxProvider`/`DisplayProvider`/`BrowserProvider`/`FileScanner` implementation: implement the relevant interface (see [architecture.md](architecture.md#provider-architecture)), register it via configuration, and add it to [DEPENDENCIES.md](../DEPENDENCIES.md). Core session/policy code must not import the concrete provider's SDK directly.

## Coding standards

Services and clearly defined interfaces over God classes; business logic stays out of UI components and controllers; no direct container-runtime calls from the backend (see [ADR 0005](adr/0005-no-docker-socket-in-backend.md)); centralized authorization and policy evaluation (no duplicated permission checks); typed events, not magic strings; schema-validated inputs; migrations for all schema changes; linting and automated tests are part of "done," not optional cleanup.
