# OpenRBI Productization v0.1.1 — User/Admin Plane Separation Analysis

> **Status: analysis only.** No code, configuration, Docker Compose file, migration, or existing documentation was changed to produce this report. Nothing described as "recommended" or "proposed" below is implemented. Where this document proposes new ADRs, it proposes their *content*, not their adoption — no ADR files were created under `docs/adr/`, since that directory represents decisions already made in this project, and none has been made here.
>
> Every claim below is grounded in the actual repository state at the time of writing (commit `27b27c2` and the working tree at analysis time), verified by reading the cited files directly — not assumed from the master brief, from `docs/architecture.md`, or from this task's own example diagrams. Where the actual code differs from what a doc implies, that's called out explicitly.

## Executive Summary

OpenRBI's backend is a single FastAPI process, on a single Docker network, behind a single reverse-proxy listener — there is no network boundary between "user" and "admin" API surfaces today, only role-based `403`s enforced per-endpoint. That sounds worse than it is: nearly every property this task's proposed architecture is *trying* to achieve already exists for a different reason. No client (browser, and by extension any future portal) ever talks to PostgreSQL, Redis, the Session Agent, or quarantine storage directly — everything is mediated by the backend's own HTTP API, because that's simply how the app was built, not as a security control. The Session Agent already can't be reached by anything except the backend process, authenticated by a static shared token the browser never sees. The browser sandbox's network isolation — the thing this task calls a "Browser Isolation Zone" — already exists today as the `browser-plane` Docker network plus `scripts/setup-network-isolation.sh`'s blocklist; it is not a gap. The one real gap is that the *reverse proxy* doesn't distinguish an admin request from a user request at the network layer — anyone who can reach the public ingress can reach `/admin/*` at the TCP level, and only application-layer RBAC stops them from doing anything once there. Splitting that off is a real, low-cost improvement, but it doesn't require rewriting the backend, splitting the database, or standing up a third network zone. Recommendation: prepare for a Two-Zone split now (cheap, mostly proxy/router-registration changes), defer actually operating separate deployments/VLANs until there's a real second portal to put behind them, and do not build a third Browser Isolation Zone — it already exists in substance.

## 1–2. Reading the request against the actual repo

The request's proposed three-zone diagram and its example ACL table (`Internet → Admin Portal DENY`, etc.) are treated here as a hypothesis to test, not a starting assumption — per the instructions, nothing from the prompt is taken as already true. Sections 3–14 below work through the actual code; the comparison against the proposed model appears in section 6 onward.

## 3–4. Current Architecture and Trust Boundaries (as implemented)

### Process/network topology (`docker-compose.yml`)

```
control-plane (172.28.0.0/16)              browser-plane (172.30.0.0/24, no IPv6)
┌─────────────────────────────────┐        ┌──────────────────────────────┐
│ postgres   redis   clamav       │        │ per-session sandbox          │
│ session-agent                   │        │ containers (Firefox+VNC)     │
│ backend ───────────────┐        │        │                              │
│ frontend  reverse-proxy│        │        │                              │
└─────────────────────────┼───────┘        └───────────────▲──────────────┘
                           └── backend, pinned 172.30.0.2 ──┘
                               (display relay only; see below)

Internet ──(8080, or 443/80 via docker-compose.prod.yml)──▶ reverse-proxy
                                                                  │
                                          ┌───────────────────────┼───────────────────────┐
                                          ▼                                               ▼
                                   proxy_pass /                                 proxy_pass /api/*, /api/display/*
                                   → frontend:80 (static SPA)                   → backend:8000 (one process, one port)
```

**Every** control-plane service — Postgres, Redis, ClamAV, the Session Agent, the backend, the frontend's nginx, and the reverse proxy — sits on the *same* Docker network, `control-plane`. There is no internal segmentation among them today; whatever isolation exists between e.g. the backend and Postgres is entirely at the credential/application layer (a DB password, argon2-hashed and checked per-connection), not the network layer. `browser-plane` is the one genuinely separate network, and it already gets real enforcement: `scripts/setup-network-isolation.sh` blocks it from RFC1918/link-local/loopback/every other Docker network/the host's own IPs, permits only established-return traffic back into `control-plane`, and exempts exactly one address (`172.28.0.2`→`172.30.0.2`, the backend's pinned NIC) to allow new connections *out* to a sandbox for the display relay — see `docs/security-model.md#network-isolation` for the verified detail. This is the one place a real network-layer trust boundary already exists in this codebase.

### Who can reach what

- **Reaches PostgreSQL**: only the backend (`backend/app/db/session.py`, `create_async_engine`). The Session Agent has no `DATABASE_URL` at all (`session-agent/app/config.py` — no such field exists). Nothing else on `control-plane` is a Postgres client.
- **Reaches Redis**: only the backend (`backend/app/core/redis.py`). Sessions, MFA-pending state, the Phase 20 login-lockout counters, and release tokens are the only things stored there. The Session Agent doesn't touch it.
- **Reaches the Session Agent**: only the backend, via `backend/app/core/session_agent_client.py`, authenticated with a static bearer token (`X-Openrbi-Agent-Token`) compared with `hmac.compare_digest` (`session-agent/app/auth.py`). This token lives only in each service's own `.env` — it is never sent to, or held by, any browser client. Nothing a user's request supplies is passed to the Session Agent unvalidated: `app/services/sessions.py`'s `create_session`/`isolate_session`/`terminate_session` always resolve the caller's *own* `current_user`/ownership first, then issue a request carrying only the already-validated session id.
- **Reaches the Docker host indirectly**: only the Session Agent, via the bind-mounted `/var/run/docker.sock:ro` (`docker-compose.yml`). The backend explicitly never gets this mount ([ADR 0005](../adr/0005-no-docker-socket-in-backend.md)).
- **noVNC path**: browser → reverse proxy (`/api/display/{id}/ws`, WebSocket) → backend (`app/api/display.py`) → a plain outbound TCP connection from the backend's pinned `browser-plane` address to the sandbox's VNC port. The backend is the only thing that ever dials a sandbox's VNC port; the client never gets a direct route to it.
- **HTTPS termination**: at the reverse proxy only — `docker/nginx/nginx.conf` (dev, plain HTTP) or `docker/nginx/nginx.tls.conf` (the Phase 22 production overlay, TLS on 443). Every other hop (proxy→backend, proxy→frontend, backend→session-agent, backend→sandbox) is plain HTTP/TCP inside `control-plane`/`browser-plane` — there is no service-to-service TLS in this codebase today.
- **Authentication**: exactly one place, `app/api/auth.py`'s `/auth/login` (+ `/auth/mfa/verify`, `/mfa/setup/confirm`). Produces a server-side Redis-backed session token, delivered as an `httponly`, `samesite=lax` cookie with no explicit `domain=` (so it's scoped to whatever host the reverse proxy answers on).
- **Authorization**: exactly one mechanism, `app/core/deps.py`'s `require_role(*names)`, applied as a FastAPI dependency — either at the router level (most admin routers: `app/api/admin.py`, `admin_sessions.py`, `admin_quarantine.py`, `admin_incidents.py`, `admin_nodes.py`, `admin_audit.py`, `admin_health.py`, and `app/api/policies.py` despite its non-`admin_`-prefixed filename) or per-endpoint (`app/api/mfa.py`'s single admin-only `POST /mfa/admin/users/{id}/reset` inside an otherwise user-facing router — the one router today that mixes both). Ownership checks (a resource belonging to someone else is `404`, not `403`) are a second, separate mechanism layered on top for user-facing endpoints (`app/api/sessions.py`, `app/api/files.py`, `app/api/display.py`).
- **APIs mixing user and admin functions**: `app/api/mfa.py` is the only one (see above). Every other router is cleanly one or the other at the router level — this is a much better starting point than the prompt assumes.
- **Privileged endpoints**: everything under `/admin/*` (12 routers, all gated by `require_role`), plus `POST /admin/nodes/*`, `POST /admin/sessions/*/kill` (ADMIN-only, stricter than the rest), and the Session Agent's own internal API (never exposed through the reverse proxy at all — `docker-compose.yml` publishes no port for `session-agent`).
- **Upload/download data paths**: both are entirely mediated by the backend. Downloads: sandbox → Session Agent (`exec`, not the Docker archive API — tmpfs limitation, see `docs/quarantine.md`) → backend's poller (`app/core/download_poller.py`) → hashed/detected/policy-checked → staged to the `quarantine-staging` Docker volume, mounted **only** into the backend container (`docker-compose.yml`'s `volumes: - quarantine-staging:/app/data`) → `QuarantineFile` row. Uploads: client → `POST /sessions/{id}/uploads` → same hash/detect/policy/scan chain → written into the sandbox via the Session Agent's `exec`+raw-stdin-socket path (`write_upload`). **No client, present or future, ever gets a filesystem path to quarantine storage** — the only route back to the user is `POST /files/{id}/download-token` (Redis `GETDEL`, single-use, 5-minute TTL) + `GET /files/download/{token}`, which streams bytes through the backend process, not a shared mount.

## 5. Blast Radius

**Scenario A — a future User Portal is compromised.** Today there is no User Portal to compromise, so this is necessarily about the equivalent capability: an attacker with a valid, unprivileged USER session (or, worse, RCE inside whatever process terminates the user's HTTP requests). Given the architecture above:
- **Admin API**: blocked by `require_role` — RCE in the process *does* let an attacker call admin endpoints with the process's own DB session, since `require_role` only checks the *caller's* role from their cookie, not the process boundary. If the compromised code can forge or reuse an admin's session token (e.g., by reading Redis, which the same process can already reach), RBAC provides no protection. **This is the core finding**: today, RBAC is an application-layer control running *inside* the same trust boundary as the thing it's meant to constrain from a different plane. It stops a normal user from *clicking* their way to admin functions; it does not stop code-execution-level compromise of the API process itself from reaching them, because there is only one process.
- **PostgreSQL / Redis**: directly reachable over the network from wherever the backend process runs (same subnet), and the backend already holds live credentials for both. A compromise of the backend process is a compromise of both, full stop — there's no network hop to fail here today.
- **Session Agent**: reachable over the network (same subnet) and the backend process already holds the shared bearer token in its own environment — a code-execution compromise of the backend can read that token from its own process environment and call the Session Agent directly, including `isolate`/`terminate` on *any* session id (the Session Agent's own auth only checks the token, not which BrowserSession the caller "owns" — ownership is a backend-side check the Session Agent has no way to independently enforce).
- **Docker host**: not directly — the backend has no socket access — but *indirectly* via the Session Agent, per the above, since a backend compromise already yields Session-Agent-level control, and the Session Agent's whole job is issuing Docker API calls.
- **Quarantine / Audit**: same story — reachable, because they live inside the same process/volume the backend already has full access to.
- **Other users' sessions/data**: yes — ownership checks are backend-side application logic; a backend process compromise trivially bypasses them (it's the same code that enforces them).

**Scenario B — a browser sandbox is compromised.** This is the scenario the codebase already defends well:
- **User Plane / Control Plane / Admin Plane / Host**: `browser-plane`'s blocklist (verified live, `docs/security-model.md`) denies the sandbox any route into `control-plane`'s subnet, the host's own IPs, or any other Docker network on the host. The only *inbound* new-connection exception is the backend's pinned address, and that's the backend reaching *in* to the sandbox's VNC port, not the reverse. A compromised sandbox cannot reach Postgres, Redis, the Session Agent, or any other sandbox by design, and this has been verified against the live iptables rules, not just asserted.
- **Quarantine / Database**: unreachable for the same reason — no network path exists.
- This scenario is already well-mitigated by the existing `browser-plane` design; a third "Browser Isolation Zone" in the sense this task's diagram means (a distinct network segment for browser nodes) **already exists**.

**Scenario C — an authenticated normal user tries admin endpoints.** Today: `require_role` returns a clean `403`, verified repeatedly in this project's own test suite (`backend/tests/integration/test_authorization.py`, `test_admin_session_control.py`) and its Phase 21 security-test script. **Is an additional network boundary worthwhile beyond this?** For *this specific* threat (a legitimate but curious/malicious end-user, no code execution), no — RBAC alone already fully closes it, and a network ACL would be a second, mostly redundant control against the same attacker capability. A network boundary earns its keep against **Scenario A's actual threat** (code-execution-level compromise of whatever process serves the User Portal), not against Scenario C's.

## 6. Deployment Model Comparison

| | **A — Current/Monolithic** | **B — Two Zone** (DMZ: user portal + display gateway / Trusted: admin + core + DB + quarantine + session control) | **C — Three Zone** (adds a distinct Browser Isolation Zone) |
|---|---|---|---|
| Security | RBAC-only boundary between user/admin; no boundary against process-level compromise | Closes Scenario A materially: a compromised user-facing process no longer holds live DB/Redis/Session-Agent credentials | Marginal *additional* gain over B — the browser-plane isolation this would formalize already exists at the network layer today |
| Blast radius | Full (single process holds everything) | User-plane compromise ⇒ no direct DB/Session-Agent/quarantine access (see §17) | Same as B for this specific concern; browser-sandbox blast radius is already contained regardless of model |
| Complexity | Lowest | Moderate: one more listener/vhost, one more deployment unit, no new stateful component | Higher: a third network + a rationale for why it's distinct from what `browser-plane` already does |
| Dev effort | None | Low–Medium (see §16) | Medium–High, and mostly re-labeling an existing control, not building a new one |
| Ops effort | Lowest | Two things to deploy/monitor instead of one | Three, plus the existing `browser-plane`/iptables machinery must be reconciled with whatever the new zone's boundary is meant to be |
| Debugging | Simplest (one process, one log stream) | Slightly harder (two processes to correlate) | Harder still, without a clear matching increase in caught threats |
| Homelab fit | Best | Still fine — Compact profile (§14) keeps this achievable on one host | Poor fit without a concrete reason; adds a network the operator must reason about for no new capability |
| SMB/KMU fit | Weak (no separation story to tell a security-conscious customer) | Good — the story customers actually ask for ("can a compromised user-facing thing reach my database?") gets a real answer | Diminishing returns for this audience |
| Enterprise fit | Weak | Good foundation; VLAN/firewall enforcement is an ops-side addition on top of an already-correct app-level split | Enterprises with existing DMZ/sandbox-network conventions may want to formalize this anyway — reasonable *later*, not blocking now |
| Multi-node readiness | Unaffected either way — `BrowserNode`/`select_node()` are already abstracted (docs/architecture.md#multi-node-readiness) | Unaffected — multi-node scheduling is orthogonal to which zone the API listener runs in | Unaffected, same reasoning |

## 7. Is a third Browser Isolation Zone needed for v0.1.1?

No — building one from scratch would mean re-solving a problem that's already solved. `browser-plane` **is** the browser isolation zone this task describes, just implemented as a Docker network + iptables blocklist rather than a labeled "zone" in an architecture diagram. The only real gap between the current implementation and the task's three-zone picture is *documentation framing*, not missing enforcement — `docs/architecture.md`'s trust-boundary diagram already shows this exact separation, and `docs/security-model.md#network-isolation` documents the verified rule set. Recommendation: do not build a new zone; if anything, retitle/cross-reference the existing `browser-plane` documentation so a reader maps it onto this vocabulary, but that's a docs task, not an architecture task, and per this task's own scope restriction, not undertaken here.

## 8. API Coupling

- **Cleanly role-separated already?** Yes, at the *router* level, with one exception (`mfa.py`'s single admin sub-route, noted in §4).
- **Shared controllers?** No — every admin router (`admin*.py`, `policies.py`) is a distinct FastAPI `APIRouter` instance; none is shared with a user-facing router.
- **Shared services?** Yes, deliberately — e.g. `app/services/sessions.py`'s `isolate_session`/`terminate_session` are called by the admin router, but `create_session`/`terminate_session` (self-service) are called by the user router; they share the underlying `BrowserSession` model and lifecycle logic, not duplicate it. This is good, intentional reuse, not accidental coupling — splitting the *routers* onto different listeners would not require splitting these services.
- **Can user/admin endpoints go on different listeners?** Yes, with a small, contained change: `app/main.py` currently does one unconditional `app.include_router(...)` per router at import time. Gating that behind a runtime flag (e.g., two `main.py` entry points, or one `main.py` reading `OPENRBI_LISTENER_MODE=user|admin|both` and skipping the admin `include_router` calls when not `admin`/`both`) is a small, mechanical change confined to `app/main.py` — no service, model, or business-logic file needs to change.
- **Must services be split?** No — see above.
- **Is different routing (same process) enough, or is a separate deployment needed?** Different *routing* (nginx `location` blocks pointing at the same backend:8000, gated by source IP/VLAN at the proxy) would already deliver the RBAC-redundancy benefit for Scenario C, but does **nothing** for Scenario A, because the same single process still holds every credential regardless of which route a request arrived through. The real Scenario-A benefit requires two separate **processes** (so a compromise of the one serving user traffic doesn't inherit the other's environment/credentials) — but they can absolutely be the *same codebase*, run twice with different startup flags. A full second deployment (separate container image, separate build) is not required; a second container from the *same* built image with a different environment variable is.
- **Physically necessary?** Not for v0.1.1. The credential-separation benefit (the actual point of Scenario A) is achievable by running two instances of the same image with different env vars and, ideally, different DB roles (see §11) — no separate codebase, no separate repo, no microservice split.

## 9–10. Admin Portal / User Portal (neither exists yet — profiles for when they do)

**Admin Portal**, once built, should be served from its own vhost/origin (e.g. `openrbi-admin.internal`) reachable only from a management network — this is an ops-side (reverse-proxy + firewall) decision, not a backend rewrite, given the finding in §8 that admin routing can already be isolated by listener/vhost without touching business logic. Session cookies naturally help here: the current cookie has no explicit `domain=` (§4), so once served from a distinct origin it is automatically origin-scoped by the browser — an XSS in whatever serves the user-facing origin cannot read a cookie set for the admin origin, at no extra engineering cost.

**User Portal**, once built, needs — and today already only gets, because no client has anything else — exactly: `POST /auth/login`, MFA endpoints, `GET /auth/me`, `POST/GET /sessions*`, `POST /sessions/{id}/uploads`, `GET /files/me`, `POST /files/{id}/download-token`, `GET /files/download/{token}`, the `/display/{id}/ws` WebSocket, and `POST /auth/logout`. This is already the *entire* set of endpoints a USER-role account can reach (every other router 403s it) — the "minimal API profile" this task asks to derive already exists as a natural consequence of the current RBAC design; it doesn't need to be constructed.

## 11. Database Access

The preferred model in the prompt — `User Portal → restricted API → Core Services → PostgreSQL` — **is already exactly how the code works.** No user-facing code path, and by construction no future User Portal frontend, ever gets a database connection string or a SQL client; `app/db/session.py`'s engine is instantiated once, inside the backend process, and nothing outside that process holds `DATABASE_URL`. The only thing not yet true is *process*-level separation between the code path that happens to serve `/admin/*` and the one serving `/sessions*` (§4/§8) — but both already reach Postgres exclusively through the same SQLAlchemy layer, with no raw/ad-hoc query path anywhere that a portal could accidentally get pointed at directly. Same conclusion for Redis (`app/core/redis.py`, same single-`lru_cache`d-client pattern). **No refactor is required here for correctness** — the only possible refinement, and it's optional, is a distinct, more restricted Postgres role for a hypothetical "user-listener" process instance (§8) so a compromise of *that* instance doesn't inherit the same DB grants an admin-listener instance would need (e.g., no `DELETE` on `security_events`, no access to `role_id`/`totp_secret_encrypted` columns) — genuinely valuable in a Two-Zone model, genuinely optional for v0.1.1.

## 12. Quarantine

Already in the Trusted zone in every sense that matters: the `quarantine-staging` volume is mounted **only** into the `backend` service (§4) — not the frontend, not the reverse proxy, and (once a separate admin/user listener split existed) it would need to stay mounted into whichever instance(s) run the download/upload/release code paths, i.e. the trusted side. The current file-release-token model (Redis `GETDEL`, single-use, backend-streamed) is **already** fully compatible with "User Portal never gets filesystem access to quarantine" — it was built that way from Phase 15 onward for an unrelated reason (never trust a client-visible path to a file it hasn't been explicitly, single-use authorized for) that happens to satisfy this requirement completely. No change needed.

## 13. Session Agent

Already effectively "Trusted-only" — see §4's "Reaches the Session Agent" finding. The prompt's preferred flow —

```
User → User API → validated session request → Control Plane → Session Agent
```

— **is the current flow**, verbatim: `app/api/sessions.py`'s `POST /sessions` calls `app/services/sessions.py`'s `create_session(db, current_user)`, which resolves quota/node selection *before* ever constructing a `session_agent_client` call. A normal user never gets a message straight to the Session Agent; they get a validated, backend-mediated one. The only real residual risk (identified in §5, Scenario A) is that the Session Agent's own authentication (a single shared bearer token, checked with no notion of *which* session a caller is allowed to act on) means a *compromise of the backend process itself* — not a normal user, and not a network-adjacent attacker without that token — could issue an isolate/terminate for an arbitrary session id. Splitting user-listener and admin-listener instances (§8) would not fully close this either, unless the user-listener instance's Session Agent calls were scoped to *only* the create/start/status operations it needs for self-service, with isolate/terminate reachable only from an admin-listener instance holding a *separate* Session Agent token. That's a real, concrete hardening opportunity if/when the two-listener split happens — not required for v0.1.1's actual current usage pattern, since there is no public multi-tenant deployment yet exercising this gap.

## 14. Compact vs. Segmented Deployment Profiles

Yes, both are realistically maintainable from **one** codebase — this is the central enabling fact of the whole analysis: nothing found above requires a service split, a second repository, or divergent business logic. **Compact**: today's `docker-compose.yml`, unchanged. **Segmented**: the same image(s), with (a) `app/main.py` conditionally registering admin routers per §8, (b) a second nginx vhost/reverse-proxy instance routing only to the admin-mode listener, reachable only from a restricted network, and (c) optionally a second, more restricted DB role per §11. Both profiles differ only in *how many times* the same built artifacts are instantiated and *how* the reverse proxy/firewall routes to them — not in what's inside those artifacts.

## 15. Recommendation for v0.1.1

**Option 3 — minimal preparatory refactoring now, full segmentation later — is the right call**, for a reason more specific than "avoid overengineering": the one preparatory change that matters (gating router registration behind a listener-mode flag, §8) is *cheap only before* two portal frontends exist and start hard-coding assumptions about a single base URL/origin for everything. Doing Option 1 (build both UIs on the current single-listener architecture, split later) risks exactly the kind of "expensive after the fact" work this task asks to flag: both future frontends' API clients, CORS-adjacent assumptions, and deployment docs would need updating once a split happens, instead of being built against the eventual shape from day one. Doing Option 2 in full (stand up real Trusted/DMZ network segments, VLANs, separate DB roles, before any UI exists to justify them) is premature for a project whose own scope explicitly excludes SIEM/HA/multi-node in v0.1.1 and whose primary near-term audience (per `README.md`'s own stated goals) includes homelab/single-host deployments.

## 16. Effort Estimate (for the recommended Option 3 preparatory work)

| Area | Effort | Notes |
|---|---|---|
| Backend | **LOW** | Gate `app/main.py`'s `include_router` calls behind a mode flag; no service/model changes (§8) |
| Frontend | **LOW** (none needed yet — no UI exists) | Future portals should be built *against* the eventual split (separate base URLs) from their first commit — cheap now, expensive as a retrofit |
| Deployment | **MEDIUM** | New compose service entry (second backend instance) + a second nginx vhost/location config; no new stateful component |
| Networking | **LOW–MEDIUM** | Reusing the existing `control-plane` network is fine for v0.1.1; a real VLAN/firewall boundary is an operator-side decision for Segmented deployments, not something this repo needs to build |
| Authentication | **NONE** | Already listener-agnostic; no change |
| Authorization | **LOW** | `require_role` is unchanged; only *which routers exist in which process* changes |
| Session Management | **NONE** | Redis-backed sessions are already shared/central; unaffected by which listener a request arrives on |
| File Pipeline | **NONE** | Already fully backend-mediated (§12); unaffected |
| Testing | **LOW–MEDIUM** | `backend/tests/` would gain a check that the admin-mode listener 404s (not just 403s) admin routes when running in user-mode, and vice versa |
| Documentation | **MEDIUM** | See §20 |

**Changes that are cheap now but would get expensive later:** designing the *first* version of a User Portal frontend to already call a distinct base URL/origin for anything user-facing (even if, for v0.1.1, that origin is served by the exact same process as the admin routes) — retrofitting a hard-coded single-origin SPA after the fact touches every API call site instead of one config value.

## 17. Security Benefit (concrete, not "more secure")

- `Compromise [a future user-listener instance] → no direct Admin API access`: **new benefit** — today a backend compromise reaches every admin route in the same process; a split listener with admin routers never registered in the user-mode process makes those routes not exist to reach, not merely 403 them.
- `→ no DB access`: **partial benefit, optional** — DB access remains (the user-listener still needs it for its own endpoints), but a *restricted* DB role (§11) would deny it the admin-only columns/tables (role changes, other users' `totp_secret_encrypted`, etc.) — genuinely new, but requires the optional DB-role work, not just the listener split.
- `→ no direct Quarantine access`: **already true today**, unaffected by any of this (§12) — no benefit to claim, because there was never a gap.
- `→ no direct Session Agent access`: **already true today** for *ordinary* use (§13) — the listener split closes the *remaining* risk (a compromised process using the shared token for isolate/terminate on arbitrary sessions) only if paired with per-listener Session Agent tokens/scopes, which is a further optional step, not automatic from the split alone.
- **Cross-origin cookie isolation** (§9): a genuinely free benefit of serving admin/user on separate origins, requiring no code change (the cookie already has no explicit domain).

## 18. Complexity Guardrail

None of the above requires Kubernetes, a service mesh, new PKI, additional microservices, multiple databases, or new network topology beyond what `docker-compose.yml` already has. The recommended path reuses the existing `control-plane` network, the existing single Postgres instance, and the existing codebase, twice.

## Findings (summary)

1. No network boundary exists between admin and user API traffic today; RBAC (`require_role`) is the only control, and it does not protect against process-level compromise of the backend itself.
2. Every property the prompt's model wants for "User Portal never touches DB/Redis/Session-Agent/Quarantine directly" is **already true**, as an incidental consequence of the current single-API-process design, not a security control that was deliberately built for this purpose.
3. The proposed "Browser Isolation Zone" **already exists**, as the `browser-plane` Docker network + iptables blocklist, verified live.
4. `app/api/mfa.py` is the one router mixing an admin-only endpoint into an otherwise user-facing router — worth a note, not a redesign.
5. Splitting the listener that serves admin vs. user routes is a small, contained, `main.py`-scoped change; it does not require splitting services, models, or the file/session/quarantine pipelines.
6. The residual Session-Agent risk (shared static token, no per-caller scoping) is not closed by a listener split alone — it needs a further, optional step (per-listener tokens/scopes) that is worth flagging for later but is not urgent given no public multi-tenant deployment exists yet.

## Deployment Options — see §6 table above.

## Migration Risk

None of the working, DoD-tested subsystems — authentication, TOTP, session lifecycle, the browser sandbox, noVNC, the download/upload pipelines, quarantine, incidents, audit, security events — need to change for any option evaluated here. The one touched file for the recommended preparatory step is `app/main.py` (router registration); everything else is additive (a new compose service entry, a new nginx location block) or purely operational (network/firewall policy). This is the central reason Option 3 was chosen over Option 2: it gets the one cheap, forward-compatible change in now without touching anything the DoD walkthrough already exercised end-to-end.

## Productization Impact

- **User Portal**: should be built from day one assuming its own base URL/origin, even though nothing forces that split to be live in v0.1.1.
- **Admin Portal**: same, plus should assume it will eventually sit behind a restricted network — no code consequence today, a deployment-doc consequence later.
- **Deployment**: `docs/deployment.md` would eventually need a "Segmented" profile section alongside its current (Compact-only) instructions.
- **Documentation**: see §20.
- **Multi-node**: unaffected either way (§6) — this analysis and multi-node scheduling are orthogonal concerns.

## Suggested Implementation Order (planning only)

1. Add the `OPENRBI_LISTENER_MODE` (or equivalent) flag to `app/main.py`; verify both modes still pass the existing `backend/tests/` suite plus a new listener-mode test.
2. Build the User Portal frontend against its own configured base URL/origin (even if that origin is, for now, served by a `both`-mode listener).
3. Build the Admin Portal frontend the same way.
4. Only once both exist: stand up the second compose service + nginx vhost, and document the Segmented deployment profile.
5. Optional, later: per-listener Postgres roles and per-listener Session Agent token scopes, if/when a real multi-tenant or higher-assurance deployment need arises.

## Decision

```
PREPARE FOR SEGMENTATION, IMPLEMENT LATER
```

Technical justification: the current codebase already delivers most of the requested security properties as an accidental consequence of its single-API-process design (§11–§13); the one real, missing property (a network boundary against process-level compromise of that single process) is addressed by a small, `main.py`-scoped preparatory change (§8) that costs little now and would cost meaningfully more once two portal frontends already assume a single origin. Standing up actual VLANs/separate deployments now, before either portal exists to justify them, would be premature complexity against this project's own stated homelab/KMU-first scope (§18) and its explicit non-goals (no Kubernetes, no service mesh, no HA in v0.1.1).

## 20. Documentation Impact Review

Documents that would need updates **once** (and only once) segmentation is actually implemented — none were touched to produce this report:

- **README.md**: "Architecture overview" section would gain a one-line mention of the Segmented deployment profile once it exists.
- **docs/architecture.md**: the trust-boundary diagram already shows control-plane/browser-plane; it would gain a third box (or annotation) for the admin-mode listener once split. The "Multi-node readiness" section's reasoning pattern (abstract seam, single instance today) is the right model to reuse for this too.
- **docs/threat-model.md**: the "Compromised OpenRBI web application" attacker-model row would be updated to distinguish user-listener vs. admin-listener compromise once the split exists.
- **docs/security-model.md**: would gain a section analogous to "Control-plane container hardening (Phase 20)" for whatever the listener-split's own hardening looks like.
- **docs/deployment.md**: would gain the Segmented profile instructions (§16's deployment/networking effort).
- **docs/admin-guide.md** / **docs/user-guide.md**: would each note their respective portal's intended network reachability once real portals exist.
- **docs/development.md**: would gain a new phase/entry once this is actually built, following this project's existing per-phase changelog convention.
- **SECURITY.md**: "Security assumptions" section would be updated once the assumption "the control plane is a single trust domain" is no longer quite accurate.
- **Docker/deployment docs** (`docker-compose.yml`'s own comments, `docker-compose.prod.yml`): would need the new service/vhost documented in place, following this project's existing comment-density convention.

### Proposed ADRs (content proposed here; **no ADR files created** — see the status note at the top of this document)

- **ADR — User Plane vs. Admin Plane Separation**: would record the decision (if and when made) to split `app/main.py`'s router registration by listener mode, the rationale in §8/§17 above, and explicitly the *rejected* alternative of a full microservice split (not needed — same codebase, different process instantiation).
- **ADR — Compact vs. Segmented Deployment**: would record that both profiles are maintained from one codebase (§14), which profile is the default, and the operator-facing tradeoffs from §6's comparison table.
- **ADR — Browser Isolation Zone**: would *not* record a new zone — it would instead retroactively document that `browser-plane` (already covered by no prior dedicated ADR, only inline `docker-compose.yml` comments and `docs/security-model.md` prose) already serves this role, closing a real documentation gap (a network boundary this consequential arguably should have had its own ADR from Phase 9 onward) independent of anything else in this analysis.

## 21. Preserving the Working MVP

Every subsystem the Definition-of-Done walkthrough exercised — local auth, TOTP, session lifecycle, the browser sandbox, noVNC, the download/upload pipelines, quarantine, incidents, audit, security events — is left untouched by the recommended path. The only concrete justification offered anywhere in this analysis for touching *any* existing file is §8's `app/main.py` router-registration point, and the justification is specific: that file is the one place a trust-boundary property (which process a router's code runs in) is decided, and nowhere else. No other file's business logic is implicated by the trust-boundary question this analysis was asked to answer.
