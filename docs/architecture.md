# Architecture

## Status

All 22 build phases (see [development.md](development.md)) are complete, and Productization v0.1.1 has added a real User Portal and Admin Portal on top of them. The one deliberate deviation from this document's original sketch: there is no separate **Worker** service/container — background jobs (the download poller, incident aggregation) run as in-process asyncio background tasks inside the backend (`app/core/download_poller.py`), not a distinct deployment unit. This was a simplification made once real usage showed the job volume didn't warrant a separate process, and it can be split out later without changing any caller — nothing in the codebase assumes "in the same process" beyond that module.

## Components

| Component | Role | Status |
|---|---|---|
| Frontend | Two React/TypeScript SPAs — User Portal and Admin Portal (see below) | done |
| Backend/API | FastAPI service: auth, users, groups, policies, sessions, incidents, quarantine, audit, health | done — one codebase, runnable as `both`/`user`/`admin` listener modes (see below) |
| PostgreSQL | Durable store for all persistent entities (§27/§28) | done |
| Redis | Transient state: server-side sessions, MFA/login-lockout state, release tokens | done |
| Background jobs | Download polling, incident aggregation | done, in-process (see note above, not a separate Worker) |
| Session Manager | Backend module owning `BrowserSession` lifecycle and state transitions (`app/services/sessions.py`) | done |
| Session Agent | Separate privileged service; only component with sandbox-runtime credentials | done |
| Browser Sandbox | Per-user hardened Firefox container | done |
| Remote Display | noVNC + VNC backend + Xvfb inside the sandbox container | done |
| File Scanner | ClamAV daemon, wrapped by `FileScanner`-shaped client (`app/core/clamav_client.py`) | done |
| Quarantine Storage | Content-addressed local disk staging (`app/services/downloads.py`) — see [quarantine.md](quarantine.md) for the tracked simplification vs. a pluggable/S3-like abstraction | done (as scoped for MVP 1) |
| Reverse Proxy | TLS termination (production overlay), routing to backend/noVNC/websockets | done |

## Trust boundaries

```
┌─────────────────────────────── Untrusted ────────────────────────────────┐
│  End-user browser (admin or user, over HTTPS)                            │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │ HTTPS / WSS
┌────────────────────────────────────▼──────────────────────────────────────┐
│ Reverse Proxy (TLS termination)                                          │
└───────────┬───────────────────────────────────────────────┬──────────────┘
            │                                                │
┌───────────▼───────────────┐                    ┌───────────▼──────────────┐
│  Control Plane            │  internal, authenticated API   │ Browser Plane │
│  - Backend/API            │────────────────────▶│  Session Agent           │
│    (background jobs run   │                     │  (privileged: sandbox    │
│     in-process, no        │                     │   runtime credentials    │
│     separate Worker)      │                     │   ONLY)                  │
│  - PostgreSQL             │                     │                          │
│  - Redis                  │                     │                          │
│  - Quarantine Storage     │                     └───────────┬──────────────┘
│  - File Scanner (ClamAV)  │                                 │ create/start/
└────────────────────────────┘                                 │ isolate/kill
                                                    ┌────────────▼──────────────┐
                                                    │ Browser Sandbox(es)       │
                                                    │ (per-user, non-root,      │
                                                    │  no docker socket, no     │
                                                    │  internal network access) │
                                                    └────────────────────────────┘
```

Key boundary: **the backend/API never holds container-runtime credentials** (see [ADR 0005](adr/0005-no-docker-socket-in-backend.md)). It only ever talks to the Session Agent's internal authenticated API. Browser sandboxes have no path back to PostgreSQL, Redis, the Docker socket, the admin API, or quarantine storage — their only permitted egress is the public internet, mediated by the network-isolation layer (see [security-model.md](security-model.md)).

## Data flows (high level)

- **Login**: Frontend → Backend (`/auth/login`) → PostgreSQL (credential check) → Redis (session record) → signed session cookie back to client.
- **Start browser session**: Frontend → Backend → Session Manager validates policy/quotas → Backend calls Session Agent (`create_session`, `start_session`) → Session Agent invokes `SandboxProvider` → sandbox status polled/pushed back to Backend → Backend hands the client a `DisplayProvider` connection (noVNC URL/token) via the reverse proxy.
- **Download**: detected inside the sandbox → staged by the Session Agent into a per-session staging area → handed to the Backend's download pipeline (hash, MIME detection, policy pre-check, scan, final policy decision) → auto-release, quarantine, or reject (see [quarantine.md](quarantine.md)).
- **Admin session control**: Frontend → Backend → Session Agent (`isolate_session`/`terminate_session`) → Security Event + (for isolate) Incident recorded.

## Provider architecture

Core session/policy logic depends only on these interfaces (see [ADR 0003](adr/0003-provider-abstraction.md)):

- `SandboxProvider` — `create_session()`, `start_session()`, `isolate_session()`, `restore_session()`, `terminate_session()`, `get_status()`, `get_metrics()`. MVP 1: `DockerSandboxProvider`, optionally `GVisorSandboxProvider`.
- `DisplayProvider` — `prepare()`, `get_connection_info()`, `disconnect()`, `destroy()`. MVP 1: `NoVNCDisplayProvider`.
- `BrowserProvider` — browser launch/config. MVP 1: `FirefoxProvider`.
- `FileScanner` — `scan()`, `health()`, `signature_version()`. MVP 1: `ClamAVScanner`.

## Session Agent

See [ADR 0004](adr/0004-separate-session-agent.md). The Session Agent exposes an internal API (mutual-auth, not exposed publicly) for sandbox lifecycle and status/metrics, and is the only component with runtime-level privileges. Its interface is host-address-based (not "localhost-assumed"), so a later deployment can run browser nodes on separate hosts from the control plane without an interface change — see [Browser Nodes](#multi-node-readiness).

## Health monitoring (Phase 19)

`GET /admin/health` (ADMIN/SECURITY_REVIEWER) aggregates independent, non-fatal checks of every component named in §25 of the project brief: API, PostgreSQL, Redis, Session Agent, sandbox runtime, browser image availability, ClamAV, and quarantine-storage writability. Each check is isolated — one dependency being down never breaks another's check or 500s the endpoint (`app/services/health.py`). Overall status is `HEALTHY` only if every component is; `UNAVAILABLE` if API or PostgreSQL itself is down (the control plane is unusable); otherwise `DEGRADED`.

The plain `GET /health` liveness probe is deliberately separate and unauthenticated: because `/admin/health` requires a DB-backed session to authenticate, it is — like every other admin endpoint — unreachable during a full PostgreSQL outage. `/health` has no such dependency, so it stays the one signal guaranteed to answer regardless of what else is down.

## User/Admin listener modes (Productization v0.1.1)

Following `docs/analysis/productization-v0.1.1-zone-separation.md`'s recommendation (`PREPARE FOR SEGMENTATION, IMPLEMENT LATER`) and [ADR 0011](adr/0011-user-admin-listener-separation.md), the backend's router registration is now conditional on `OPENRBI_LISTENER_MODE` (`user` | `admin` | `both`, default `both`) — a single, central decision in `app/main.py`, not scattered per-endpoint checks:

- **`both`** (default): every router registered, exactly MVP 1's prior behavior. This is what Compact/homelab/dev deployments use, unchanged.
- **`user`**: only shared routes (health, auth, MFA enrollment/verification) plus user-facing routes (sessions, files, display) are registered. Admin routers are never imported into this process — a request to `/admin/*` gets a plain `404` (the route doesn't exist), not a `403` (RBAC rejected it). This is the actual point: a compromise of a user-mode process has no admin route to call, regardless of what credentials it might extract from its own environment.
- **`admin`**: shared routes plus every admin router. User-only routes (sessions/files/display) are not registered.

This is a **logical/process-level** separation, not yet a network-level one: both modes still reach the same PostgreSQL, the same Redis, and hold the same Session Agent shared token when run as separate processes. See [ADR 0011](adr/0011-user-admin-listener-separation.md) for the full reasoning, and [ADR 0012](adr/0012-compact-vs-segmented-deployment.md) for how this maps onto **Compact** (today's only shipped profile) vs. an illustrative, not-yet-complete **Segmented** profile (`docker-compose.segmented.yml`, two instances of the same image, no separate DB roles/Session Agent scopes/reverse-proxy vhosts yet — see `docs/deployment.md#segmented`).

The Browser Isolation Zone this task's own preceding analysis considered building **already exists** — see [ADR 0013](adr/0013-browser-isolation-zone.md): it's `browser-plane` below, unchanged by any of this.

## User Portal and Admin Portal (Productization v0.1.1)

Two separate Vite/React/TypeScript single-page apps, `frontend/user/` and `frontend/admin/`, sharing common code from `frontend/shared/` via an npm workspace (`frontend/package.json`'s `"workspaces": ["shared", "user", "admin"]`) — not a published package, not a monolith. See [ADR 0014](adr/0014-separate-user-and-admin-portal-frontends.md) for the full reasoning.

- **`frontend/shared/`** — the `ApiClient`/`ApiError` wrapper, `AuthProvider`/`useAuth`, the shared `LoginFlow` (covers all three `/auth/login` outcomes plus MFA setup and one-time recovery-code display), `ToastProvider`, and UI primitives (`StatusBadge`, `ConfirmDialog`, table/form/loading/empty/error components) plus the brand design tokens. Not buildable on its own — it's a source-only package consumed directly by each app's own Vite build.
- **`frontend/user/`** — talks exclusively to `userApi` (`frontend/user/src/api/userApi.ts`), which only calls endpoints that exist on a `user`-mode listener: sessions, files, display, plus the shared auth/MFA routes. Routes: Dashboard, Secure Browser, Downloads, Profile/MFA. Contains zero admin functionality — verified by inspecting its own production bundle, which contains no `/admin/*` calls.
- **`frontend/admin/`** — talks exclusively to `adminApi` (`frontend/admin/src/api/adminApi.ts`), which only calls endpoints that exist on an `admin`-mode listener: users, groups, sessions, policies, quarantine, incidents, audit, health, nodes, plus the admin-only MFA reset. Routes: Dashboard, Users, Groups, Sessions, Policies, Quarantine, Incidents, Audit, System.
- Each portal has its own configurable API base URL (`VITE_API_BASE_URL`, `.env.example` in each app) — Compact points both at the same origin's `/api`; a Segmented deployment would point each at its own listener's origin, with no code change.
- **Compact build**: `frontend/Dockerfile` builds both workspace apps and serves them from one nginx image — User Portal at `/`, Admin Portal at `/admin/` (`frontend/admin/vite.config.ts`'s `base`, overridable via `OPENRBI_ADMIN_BASE_PATH` for a build meant to be served at `/` on its own origin). `frontend/nginx.conf` adds the `/admin/` `try_files` rule as a site-level addition, without touching the base image's own `nginx.conf` (preserving the Phase 20 privilege-drop hardening).

**Display relay path**: User Portal → User API's `/display/{id}/ws` (a plain WebSocket upgrade, `app/api/display.py`) → whichever process terminates that route has its own pinned leg on `browser-plane` → the sandbox's VNC port. `/display/*/ws` is a user-facing route (session/file/display are the User listener's routers, see [ADR 0011](adr/0011-user-admin-listener-separation.md)) — it is never registered on an `admin`-mode process, so the Admin listener has no reason to reach `browser-plane` at all, and doesn't: `docker-compose.segmented.yml`'s `backend-admin` isn't attached to that network.

- **Compact** (`both` mode): the single `backend` service serves everything, pinned at `172.30.0.2`, exempted by `scripts/setup-network-isolation.sh`'s default. No new isolation question arises.
- **Segmented**: `backend-user` (the process that actually owns `/display/*/ws` in this profile) is pinned at `172.30.0.4` on `browser-plane`; `backend-admin` has no `browser-plane` network at all. `scripts/setup-network-isolation.sh` accepts a space-separated `OPENRBI_BACKEND_BROWSER_PLANE_IP` override precisely so a Segmented deployment can exempt `backend-user`'s own address instead of (or in addition to) Compact's default — never a blanket allow for the whole control plane, and never an exemption for `backend-admin`, which has no legitimate reason to open a connection here. See `docker-compose.segmented.yml`'s comments and `docs/deployment.md#segmented` for the exact override command.

## Multi-node readiness

MVP 1 runs on a single Linux host, but:

- The Session Agent is addressed over the network, not assumed co-located with the backend.
- `BrowserNode` is a first-class entity (UUID, hostname, status, capacity, active_sessions, last_heartbeat, runtime, version, and — Roadmap B1.10.1 — host-wide `cpu_percent`/`ram_total_mb`/`ram_used_mb`/`node_started_at`) even though only one node exists in MVP 1.
- The scheduler has an abstract `select_node()` seam, trivially returning the single node today, but built so real multi-node scheduling can replace it later without changing callers.

Real multi-node scheduling, HA, and Kubernetes orchestration are explicitly out of MVP 1 scope (see README "Scope").

### Worker telemetry and health (Roadmap B1.10.1)

`app/core/node_poller.py` refreshes `BrowserNode` from the Session Agent's `GET /v1/nodes/self` on a fixed interval (`OPENRBI_NODE_POLL_INTERVAL_SECONDS`, default 15s) independent of session-creation traffic, using the same in-process-`asyncio.Task` pattern as `app/core/download_poller.py` — no new background-worker infrastructure. `app/services/worker_health.py`'s `compute_worker_health()` is the single, centrally-defined mapping from a node's raw state to an admin-facing `HEALTHY/DEGRADED/DRAINING/MAINTENANCE/OFFLINE` label (heartbeat-staleness checked first, before any status field is trusted) — see [ADR 0018](adr/0018-worker-telemetry-and-health.md) for the full design and why `MAINTENANCE` is a new, distinct state from `DRAINING`.

### Operations Dashboard and metrics history (Roadmap B1.10.2)

Each poll tick, `node_poller.py` also writes a `WorkerMetricSample` row (`app/models/worker_metric_sample.py`) — a small internal history table, pruned to `OPENRBI_METRICS_RETENTION_DAYS` (default 7), not a general time-series store. `GET /admin/dashboard?range=1h|6h|24h|7d` (`app/api/admin_dashboard.py`, `app/services/dashboard.py`) aggregates real session/worker/audit data into KPIs, a bucketed session-history series (`app/services/metrics_history.py`, using Postgres `date_bin()` to keep point counts bounded per range), per-worker load, and warnings — replacing `Dashboard.tsx`'s previous client-side aggregation of several list endpoints. See [ADR 0019](adr/0019-metrics-history-and-operations-dashboard.md) for the full design, including why averages/deltas are `null` rather than a fabricated `0` when there's no real data yet.

### Worker Overview and Worker Detail (Roadmap B1.10.3)

The Admin Portal's **Workers** page (`frontend/admin/src/pages/Workers.tsx`) and Worker Detail page (`WorkerDetail.tsx`) are the first UI surfaces to actually display the telemetry/health B1.10.1 added and the history B1.10.2's `worker_metric_samples` table enables — the System page previously only showed a bare drain/undrain table with no telemetry at all, and now links to Workers instead. Two new read-only endpoints support the detail view: `GET /admin/nodes/{id}` and `GET /admin/nodes/{id}/metrics?range=...` (`metrics_history.node_history()`, the same bucketing as the dashboard's session history, scoped to one node). `admin_nodes.py`'s router-level RBAC was widened from `ADMIN`-only to `ADMIN`/`SECURITY_REVIEWER` for reads, matching the dashboard's access level; the four mutating routes (drain/undrain/maintenance/unmaintenance) each carry their own explicit `ADMIN`-only dependency, so read access and mutation access are independently enforced server-side.
