# Architecture

## Status

All 22 build phases (see [development.md](development.md)) are complete as of Phase 23's final documentation pass. The one deliberate deviation from this document's original sketch: there is no separate **Worker** service/container — background jobs (the download poller, incident aggregation) run as in-process asyncio background tasks inside the backend (`app/core/download_poller.py`), not a distinct deployment unit. This was a simplification made once real usage showed the job volume didn't warrant a separate process, and it can be split out later without changing any caller — nothing in the codebase assumes "in the same process" beyond that module.

The **Admin and User portals** (frontend) remain the one component that's genuinely still just a scaffold, not fully built: every backend capability listed below is real and usable directly via its API (see [api.md](api.md), [admin-guide.md](admin-guide.md), [user-guide.md](user-guide.md)), but the React SPA itself only ships the noVNC test harness (`frontend/src/SecureBrowserTest.tsx`), not a full admin/user UI. This was a deliberate scope choice for MVP 1 — the project brief's phase order (§35) is entirely backend/infrastructure-first, and no phase in it is "build the admin/user portal UI."

## Components

| Component | Role | Status |
|---|---|---|
| Frontend | React/TypeScript SPA | noVNC test harness only — no admin/user portal UI (see above) |
| Backend/API | FastAPI service: auth, users, groups, policies, sessions, incidents, quarantine, audit, health | done |
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

## Multi-node readiness

MVP 1 runs on a single Linux host, but:

- The Session Agent is addressed over the network, not assumed co-located with the backend.
- `BrowserNode` is a first-class entity (UUID, hostname, status, capacity, active_sessions, last_heartbeat, runtime, version) even though only one node exists in MVP 1.
- The scheduler has an abstract `select_node()` seam, trivially returning the single node today, but built so real multi-node scheduling can replace it later without changing callers.

Real multi-node scheduling, HA, and Kubernetes orchestration are explicitly out of MVP 1 scope (see README "Scope").
