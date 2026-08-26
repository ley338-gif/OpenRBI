# Prompt: Roadmap to Multi-Node (Roadmap B2, proposed)

> This document is written to be pasted into a planning session (the same way
> the original Master-Auftrag was) to produce a phased implementation roadmap
> for turning OpenRBI's already-"multi-node-ready" schema into an actually
> working multi-node deployment. It is a brainstorm-derived brief, not a
> committed plan — no phase below is scoped or sequenced yet; that's the
> output this prompt is asking for.

## Goal

Today (MVP 1) OpenRBI runs exactly one Session Agent / one Docker host for
browser sandboxes. The backend, data model, and admin UI already model a
`BrowserNode` as a first-class entity "so multi-node scheduling can be added
later without a schema change" (`backend/app/models/browser_node.py`), but
the actual routing is a stub. Produce a phased roadmap (in the style of the
existing Roadmap B1.10.x items — see `docs/adr/0018-worker-telemetry-and-health.md`
and `docs/architecture.md#multi-node-readiness`) that takes OpenRBI from
single-node to N-node, one browser sandbox host pool that the control plane
schedules sessions across.

**Non-negotiables carried over from the Master-Auftrag** (do not relax these
for multi-node): fail-closed on any scheduler/agent/network failure, no
security decision in the frontend, browser sandboxes never reach
Postgres/Redis/Docker-socket/admin-API/quarantine directly, no secrets in
git, MFA still mandatory for ADMIN/SECURITY_REVIEWER, and every new
abstraction seam gets an ADR the same way `SandboxProvider`/`DisplayProvider`/
`BrowserProvider`/`FileScanner` did (`docs/adr/0003-provider-abstraction.md`).

## What already exists (don't re-build this)

- `BrowserNode` table with `hostname`, `status`, `capacity`, `active_sessions`,
  `last_heartbeat`, `runtime`, `version`, CPU/RAM telemetry, `node_started_at`
  (`backend/app/models/browser_node.py`).
- `BrowserSession.node_id` FK already exists and is populated at creation
  (`backend/app/models/browser_session.py:24`) — session-to-node affinity is
  already representable, just not yet used by the lifecycle calls that follow
  creation.
- Admin lifecycle for a node: DRAINING / MAINTENANCE / undrain / unmaintenance,
  each idempotent and security-event-logged (`backend/app/services/nodes.py`).
- Centralized health computation: `compute_worker_health()`
  (`backend/app/services/worker_health.py`) — HEALTHY / DEGRADED / DRAINING /
  MAINTENANCE / OFFLINE, single source of truth already consumed by the
  Workers list, worker detail page, and dashboard.
- Self-reporting endpoint per agent: `GET /v1/nodes/self`
  (`session-agent/app/main.py`) returns capacity/active_sessions/CPU/RAM/version,
  polled by `backend/app/core/node_poller.py` on an interval and on session
  creation.
- Admin UI already lists/inspects nodes: `frontend/admin/src/pages/Workers.tsx`,
  `WorkerDetail.tsx`.
- `docs/deployment.md`'s Segmented profile already establishes the pattern of
  a *list* of exempted backend addresses for the display relay
  (`OPENRBI_BACKEND_BROWSER_PLANE_IP` accepts a space-separated list) — a
  useful precedent for per-node network config, even though it currently
  exists for a different reason (user/admin listener segmentation, not
  multi-node).

## Where it stops being real (the actual gap)

- **Exactly one agent URL exists in config**: `session_agent_base_url` is a
  single string (`backend/app/config.py:30`), and every function in
  `backend/app/core/session_agent_client.py` opens its HTTP client against
  that one constant. There is no per-node routing anywhere in the request
  path.
- **`select_node()` doesn't select**: `backend/app/services/sessions.py:102`
  refreshes and capacity-checks *the* node; its own docstring calls itself
  "trivial today" and says real selection "can replace this body later."
  There is no query across multiple `BrowserNode` rows, no scoring, no
  tie-breaking.
- **Every post-creation lifecycle call is node-blind**: `start_sandbox`,
  `isolate_sandbox`, `restore_sandbox`, `terminate_sandbox`,
  `get_display_info`, `list_downloads`/`fetch_download`/`delete_download`,
  `write_upload` all call the single configured agent — none of them take or
  resolve a node/base_url from the session's own `node_id`.
- **Capacity is a hardcoded placeholder**: `_capacity_from_settings()` in
  `session-agent/app/main.py:74-79` just returns `10`, explicitly flagged as
  a placeholder pending a host-resource-aware scheduler.
- **Reconciliation is single-node**: `backend/app/core/orphan_reconciler.py`
  (via `list_active_sandboxes`/`list_managed_sandboxes`) walks one agent's
  inventory.
- **Network isolation is one-host-at-a-time**: `scripts/setup-network-isolation.sh`
  configures iptables on the box it runs on; nothing coordinates applying it
  consistently across N hosts or verifies all of them did.
- **The display relay assumes L3 reachability** from the backend into
  `browser-plane` (`docker-compose.yml`'s `172.30.0.0/24`, backend pinned to
  `172.30.0.2`) — that only works because today everything is one Docker
  bridge network on one host.

## Areas the roadmap needs to cover

1. **Node registry & bootstrap**
   - How does a second/Nth Session Agent host get introduced? Pre-shared
     enrollment token, admin-approved join request, or manual `BrowserNode`
     row + config? Needs a story for both "trusted homelab, one admin adds a
     host" and "don't let an attacker register a rogue node that receives
     real session traffic."
   - Per-node control-plane auth: today's `X-Openrbi-Agent-Token` — confirm
     whether it's one shared secret for all agents or needs to become
     per-node (compromise blast radius matters here, per the security-first
     principle).

2. **Config & client plumbing**
   - Replace the single `session_agent_base_url` with a real per-node
     endpoint (stored on `BrowserNode`, not just settings) and thread
     `node_id`/base_url through every `session_agent_client` call so
     lifecycle actions target the node the session actually lives on
     (`BrowserSession.node_id` already exists for this).

3. **Scheduling**
   - Turn `select_node()` into real cross-node selection: query all
     ONLINE nodes (respecting DRAINING/MAINTENANCE, which already exist),
     score by free capacity (least-loaded vs. bin-packing — pick one and
     document why), and handle the "all nodes full/offline" fail-closed path
     that already exists for the single-node case.
   - Sessions are inherently sticky to one node for their whole lifetime — no
     live migration. Roadmap should say this explicitly so it isn't assumed
     away later.
   - Replace the hardcoded `capacity = 10` with something host-resource-aware
     (or at minimum an explicit per-node config value set at deploy time,
     which is still better than a shared constant).

4. **Cross-host networking**
   - Each node's `browser-plane` subnet must not collide across hosts — needs
     per-node subnet allocation/config instead of the single hardcoded
     `172.30.0.0/24`.
   - Control-plane ↔ Session-Agent traffic now crosses host/network
     boundaries — needs a transport decision (mTLS, WireGuard/VPN overlay,
     or an operator-managed private network) instead of relying on a shared
     Docker bridge.
   - The noVNC display relay path (backend → sandbox IP) needs a design for
     "sandbox lives on a different host than backend" — likely each node's
     Session Agent proxies/relays its own sandboxes' display traffic rather
     than the backend reaching sandbox IPs directly.
   - `scripts/setup-network-isolation.sh` needs to run per-host with correct
     per-node exemption config, plus a way for the admin/health system to
     verify it was actually applied on *every* node (today's
     `/etc/openrbi/network-isolation` marker file is per-host already —
     extend the "was isolation verifiably applied" health signal to be
     per-`BrowserNode`, not just implied by the backend's own local marker).

5. **Reconciliation & health**
   - `orphan_reconciler` and the download/upload paths need to iterate every
     registered node, not one.
   - Decide what happens to sessions on a node that goes OFFLINE mid-session
     (no migration possible — admin-visible failure state and manual/forced
     termination, most likely) and make sure that's a documented, tested
     behavior, not an accidental gap.

6. **Deployment & ops**
   - Split `docker-compose.yml` so a node host can run *just* `session-agent`
     + its own network isolation, separate from the control-plane compose
     file that runs backend/postgres/redis/etc.
   - Update `docs/deployment.md#sizing` (currently single-host math) for
     N-node capacity planning.
   - Admin UI: a "register node" flow (Workers.tsx currently only lists/
     inspects existing rows).

7. **Testing**
   - Multi-node fixtures for `test_worker_health.py` / `test_admin_nodes.py`.
   - Extend `scripts/fault-injection-probe.py` / fault-injection acceptance
     docs with node-down scenarios (one of N nodes fails — sessions on it,
     scheduling onto the rest, dashboard reflects it correctly).

## Open design decisions the roadmap should surface, not silently resolve

- Least-loaded vs. bin-packing scheduling, and why.
- Per-node vs. shared control-plane auth token.
- How a node is enrolled (manual config vs. token-based self-registration)
  and what stops a rogue node from registering.
- Whether cross-host transport is mTLS, a VPN overlay, or documented as an
  operator responsibility (matches the existing "Segmented profile is
  illustrative, not yet complete" honesty pattern already used in
  `docs/deployment.md`).

## What the roadmap output should look like

Match the existing project convention: a numbered phase list (e.g.
`B2.1`, `B2.2`, ...) where each phase has a one-line goal, the files/services
it touches, and a Definition-of-Done a reviewer could check off — the same
granularity as the Master-Auftrag's Section 35 phase list and the existing
`Roadmap B1.10.x` items referenced above. Call out anywhere a phase requires
a new ADR (following the `docs/adr/000N-*.md` pattern) before implementation
starts, and flag any phase that would change the fail-closed security
guarantees so it gets extra scrutiny.
