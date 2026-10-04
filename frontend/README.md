# OpenRBI frontend

An npm workspace with the two portals and the code they share:

| Workspace | What it is |
|---|---|
| `shared/` | Source-only package: API client, login/MFA flow, UI components, styles. It has no build step; both portals alias `@shared` to it and compile it as part of their own build. |
| `user/` | User Portal: Dashboard, Secure Browser (noVNC viewer), Downloads, Profile. Talks to the User listener only. |
| `admin/` | Admin Portal: Dashboard, Users, Groups, Sessions, Policies, Quarantine, Incidents, Workers, System health, Audit log, LDAP. Talks to the Admin listener only. |
| `e2e/` | Playwright suite that drives both portals against a running stack (`scripts/e2e-run.sh`). |

React, TypeScript and Vite, no other framework. Why there are two separate apps: [ADR 0014](../docs/adr/0014-separate-user-and-admin-portal-frontends.md).

## Develop

Start the stack first (`docker compose up -d`, see [docs/development.md](../docs/development.md#frontend-development)). Then:

```bash
cd frontend
npm ci
npm run dev --workspace=user     # http://localhost:5173
npm run dev --workspace=admin    # http://localhost:5174/admin/
```

The dev server sends `/api` (including the display WebSocket) to the stack's reverse proxy at `http://localhost:8080`. Set `OPENRBI_DEV_API_TARGET` to use a different address, e.g. `OPENRBI_DEV_API_TARGET=http://localhost:8090 npm run dev --workspace=user`.

## Build

```bash
npm run build --workspace=user   # user/dist
npm run build --workspace=admin  # admin/dist
```

`npm run build` type-checks first (`tsc -b`). Build-time settings:

- `VITE_API_BASE_URL` (default `/api`) — where the portal sends API requests. See `user/.env.example` and `admin/.env.example`.
- `OPENRBI_ADMIN_BASE_PATH` (Admin Portal only, default `/admin/`) — the path the Admin Portal is served under. Set it to `/` for a build served from its own origin. It can be set in the environment or in `admin/.env`.

`frontend/Dockerfile` builds both portals into one nginx image (User Portal at `/`, Admin Portal at `/admin/`, docs at `/docs/` for the in-app Help menus). Its build context is the repository root.

## Test

The Playwright suite needs a running stack with migrations applied; `scripts/e2e-run.sh` seeds its test accounts, runs it and removes them again. See [docs/development.md](../docs/development.md) ("Tests").
