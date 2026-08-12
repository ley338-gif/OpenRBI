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
6. Session Agent
7. Browser sandbox
8. noVNC remote browser
9. Network isolation
10. Session lifecycle
11. Admin session control
12. Policy engine
13. Download interception
14. File scanner
15. Quarantine
16. Upload pipeline
17. Incidents
18. Audit/security events
19. Health monitoring
20. Hardening
21. Integration/security tests
22. Deployment
23. Final documentation review

After each phase: run tests, update documentation, record any known technical debt, and do not silently ignore a known security regression.

## Tests

Unit tests alone are not sufficient. Phase 21 requires integration/security tests covering (non-exhaustive, see the project brief §30 for the full list): sandbox cannot reach loopback/host/RFC1918/Docker API; user A cannot access user B's session or files; a disabled user cannot start a session; admin disconnect/isolate/kill all work and are audited; an isolated session has no network access; MIME `DENY` rules work; unknown file types are quarantined; forged-domain source rules (e.g. `microsoft.com.attacker.org`) do not match; scanner/policy/quarantine outages block release; release tokens are single-use and expire; admin login requires MFA; recovery codes are single-use; MFA reset and policy changes generate audit events.

## Migrations

Backend uses Alembic. Every schema change ships as a migration — no manual schema edits against a running database.

## Developing a new provider

To add a new `SandboxProvider`/`DisplayProvider`/`BrowserProvider`/`FileScanner` implementation: implement the relevant interface (see [architecture.md](architecture.md#provider-architecture)), register it via configuration, and add it to [DEPENDENCIES.md](../DEPENDENCIES.md). Core session/policy code must not import the concrete provider's SDK directly.

## Coding standards

Services and clearly defined interfaces over God classes; business logic stays out of UI components and controllers; no direct container-runtime calls from the backend (see [ADR 0005](adr/0005-no-docker-socket-in-backend.md)); centralized authorization and policy evaluation (no duplicated permission checks); typed events, not magic strings; schema-validated inputs; migrations for all schema changes; linting and automated tests are part of "done," not optional cleanup.
