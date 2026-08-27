# Roadmap B2: Multi-Node Deployment

> Produced from `docs/analysis/multinode-roadmap-prompt.md`'s planning brief.
> Every "what already exists" / "actual gap" claim in that document was
> re-verified directly against the repository (`backend/app/config.py`,
> `backend/app/services/sessions.py`, `backend/app/core/session_agent_client.py`,
> `backend/app/models/browser_node.py`, `session-agent/app/main.py`) before
> this roadmap was written — all still accurate at time of writing.
>
> **Status: all seven phases (B2.1–B2.7) implemented and merged.**
> Verification against a genuine second host (rather than a second
> container/process standing in for one on the same Docker host) remains
> an explicitly stated open item — see [ADR 0024](adr/0024-cross-host-display-relay.md)'s
> Consequences and B2.4/B2.6's own entries below for exactly what that
> gap is and isn't.

## Goal

Take OpenRBI from exactly one Session Agent / one Docker host for browser
sandboxes to N hosts that the control plane schedules sessions across,
without relaxing any of the Master-Auftrag's non-negotiables (fail-closed
on any scheduler/agent/network failure, no security decision in the
frontend, browser sandboxes never reach Postgres/Redis/Docker-socket/
admin-API/quarantine directly, no secrets in git, MFA still mandatory for
ADMIN/SECURITY_REVIEWER).

## Open design decisions (recommended, not silently assumed)

These were explicitly flagged in the planning brief as decisions the
roadmap must surface. Recommendations below, each with rationale — open to
being overridden before Phase B2.1 starts, since B2.1 is where they become
schema/code.

| Decision | Recommendation | Why |
|---|---|---|
| Scheduling strategy | **Least-loaded**, not bin-packing | Matches the project's fail-closed/spread-risk posture — bin-packing concentrates sessions onto fewer nodes, which raises the blast radius of a single node compromise or crash and complicates draining. Bin-packing can be revisited later as an explicit opt-in scoring mode if resource-efficiency ever outweighs that. |
| Control-plane ↔ Session-Agent auth | **Per-node token**, not one shared secret | The brief explicitly flags this as a blast-radius question. Today's single `OPENRBI_SESSION_AGENT_API_TOKEN` means compromising *any* node's token is equivalent to compromising all of them. Per-node tokens (encrypted at rest the same way `totp_secret_encrypted` already is, via `app/core/crypto.py`'s `encrypt_secret`) cap a leak to the one node. |
| Node enrollment | **Pre-shared enrollment token + mandatory admin approval step** (two-phase: a node presents a token to register, lands in a `PENDING` state, only an admin action flips it to active) | Matches "trusted homelab, one admin adds a host" (still just one config step) while fail-closing against "a rogue node registers and starts receiving real session traffic" — a `PENDING` node never gets scheduled onto, regardless of how it got a valid enrollment token. |
| Cross-host transport | **Documented operator responsibility: a private overlay network (WireGuard recommended) between hosts**, with per-node token auth as the application-layer control regardless of transport; mTLS documented as a future hardening option, not required for B2 | Matches the existing, deliberate "Segmented profile is illustrative, not a complete production guide" honesty pattern (`docs/deployment.md`) — OpenRBI validates that a node's configured endpoint is reachable and authenticates every call, but does not attempt to manage host-to-host network security itself, the same boundary it already draws around firewall/VLAN enforcement in the Segmented profile. |

## Phases

Each phase: one-line goal, files/services touched, Definition-of-Done, ADR
requirement, and a security-scrutiny flag where relevant.

### B2.1 — Node registry & enrollment — **done**

See [ADR 0023](adr/0023-node-enrollment-and-trust-model.md) for the
as-built decision record (token-based self-enrollment + mandatory admin
approval, per-node encrypted tokens). Verified end to end against a real
docker-compose stack, including a second real Session Agent container
self-enrolling and being approved through the Admin Portal UI.

**Goal**: Replace "one node, implicitly trusted" with a real registry that
distinguishes an enrolled, approved node from an unknown one.

**Touches**: `backend/app/models/browser_node.py` (add `endpoint_url`,
`enrollment_status` [`PENDING`/`APPROVED`/`REVOKED`], `agent_token_encrypted`),
a new Alembic migration, a new `backend/app/api/admin_nodes.py` (or extend
`admin_nodes.py` if it already exists under that name) enrollment-approval
endpoint, `backend/app/services/nodes.py`, `session-agent/app/main.py` (the
enrollment client call), `frontend/admin/src/pages/Workers.tsx` (approve/
reject UI).

**Definition of Done**:
- A new Session Agent presenting a valid enrollment token creates a
  `BrowserNode` row in `PENDING` — it does not appear as schedulable.
- An admin action (audited, `SecurityEventType`) flips it to `APPROVED`.
- An `APPROVED` node's per-node token is generated server-side, encrypted
  at rest, and never logged or returned in any API response after initial
  issuance (matches the TOTP-secret handling precedent).
- A `REVOKED` node immediately stops being schedulable and its token no
  longer authenticates.
- Integration test: an unapproved node's session-agent calls are rejected
  end to end, not just at the DB-row level.

**ADR required**: yes — `docs/adr/0023-node-enrollment-and-trust-model.md`,
recording the enrollment-token + admin-approval decision and the rejected
alternative (fully automatic registration).

**Security scrutiny**: **high** — this is the phase that decides whether a
network-adjacent attacker can get session traffic routed to a host they
control. Review should specifically try to break the PENDING→APPROVED
transition (race conditions, replay of a used enrollment token, a
REVOKED node's in-flight requests).

### B2.2 — Per-node config & client plumbing — **done**

Every `app/core/session_agent_client.py` function now accepts an optional
`connection: NodeConnection` (base_url/token); `app/services/nodes.py`'s
`connection_for_node()` resolves one from a real `BrowserNode` (decrypting
`agent_token_encrypted`) or falls back to the legacy shared settings for
a node with no `endpoint_url` (every existing single-node case,
unaffected). Wired through every session-lifecycle call site:
`create_session`/`terminate_session`/`isolate_session`/`restore_session`
(`app/services/sessions.py`), the display relay
(`app/api/display.py`), and the download/upload pipelines
(`app/services/downloads.py`/`uploads.py`). Verified with a real second
HTTP listener standing in for a second node (not the full Docker-backed
Session Agent — this phase is about routing, not sandbox lifecycle,
which the existing single-node suite already covers against the real
agent): isolate/restore/terminate all reached the second node's own
endpoint with its own decrypted token, never the default node's.

**Goal**: Every Session-Agent-bound call resolves the node it's actually
targeting instead of one hardcoded `session_agent_base_url`.

**Touches**: `backend/app/config.py` (remove/deprecate the single
`session_agent_base_url` default in favor of per-node `endpoint_url` from
B2.1), `backend/app/core/session_agent_client.py` (every function gains a
`node` or `base_url`/`token` parameter — `start_sandbox`, `isolate_sandbox`,
`restore_sandbox`, `terminate_sandbox`, `get_display_info`,
`list_downloads`/`fetch_download`/`delete_download`, `write_upload`),
every caller in `backend/app/services/sessions.py`, `app/api/files.py`,
`app/api/display.py`, `app/core/download_poller.py`,
`app/core/orphan_reconciler.py` — all currently assume the single agent.

**Definition of Done**:
- No function in `session_agent_client.py` reads a module-level/settings
  base URL directly; every call site resolves it from
  `BrowserSession.node_id` → `BrowserNode.endpoint_url` (added by B2.1,
  written at approval time but not yet read anywhere before this phase).
- Existing single-node integration tests still pass unchanged (this phase
  is plumbing, not behavior change, for the single-node case).
- New test: two nodes configured, a session created against one, its
  lifecycle calls (isolate/restore/terminate) verifiably hit that node's
  endpoint and not the other's.

**ADR required**: no (mechanical, confined to the client/caller layer per
the brief's own §8-equivalent finding for the listener split).

### B2.3 — Real scheduling — **done**

`select_node()` now queries every `APPROVED` node, refreshes each from its
own agent (via `connection_for_node()`, B2.2), and scores by free capacity
(`capacity - active_sessions`; least-loaded wins), ties broken
deterministically by lowest hostname. A node that's `DRAINING`/
`MAINTENANCE`, self-reports non-`ONLINE`, or whose agent is unreachable
this round is excluded from that round only — one bad node never blocks
scheduling onto the others. When no `BrowserNode` row exists at all yet
(a fresh install before any admin enrollment), it falls back to the
legacy single-node auto-creation path unchanged, so the very first
session ever created still needs no prior admin action. Fails closed
with the same `NoCapacityError` as before when every candidate is
excluded or full. Session Agent capacity is now real per-node deploy-time
config (`OPENRBI_AGENT_CAPACITY`, default 10 — unchanged from the
previous hardcoded value). Sessions remain sticky to their node for their
whole lifetime; no live migration (see `docs/architecture.md#multi-node-readiness`).
Verified with real HTTP listeners standing in for multiple nodes
(`test_scheduling.py`): least-loaded selection, deterministic tie-break,
fail-closed when every node is full, and one unreachable node not
blocking scheduling onto a healthy one.

**Goal**: `select_node()` stops being a single-node stub and does real
cross-node selection.

**Touches**: `backend/app/services/sessions.py`'s `select_node()`,
`session-agent/app/main.py`'s `_capacity_from_settings()`.

**Definition of Done**:
- `select_node()` queries all `APPROVED`+`ONLINE` nodes (respecting
  `DRAINING`/`MAINTENANCE`, which already exist and already work
  single-node), scores by free capacity (least-loaded, per the decision
  above), and picks the winner deterministically on a tie (e.g. lowest
  `hostname`, documented).
- "All nodes full/offline" still fails closed with the same
  `NoCapacityError` path that exists today — verified by a test with every
  configured node at capacity.
- `capacity` becomes a real per-node deploy-time config value (an
  explicit `OPENRBI_AGENT_CAPACITY` env var is the minimum viable version;
  host-resource-aware auto-sizing is explicitly out of scope for B2 and
  should be logged as a follow-up, not silently dropped).
- Documented, explicit statement (in this file and `docs/architecture.md`)
  that sessions are sticky to one node for their whole lifetime — no live
  migration in B2.

**ADR required**: no — extends an already-documented seam
(`docs/architecture.md#multi-node-readiness`).

### B2.4 — Cross-host networking & display relay redesign — **done (single-host verified only — see caveat below)**

See [ADR 0024](adr/0024-cross-host-display-relay.md) for the full
as-built decision record. Summary: the noVNC relay now terminates at
each node's own Session Agent (`WS /v1/sandboxes/{id}/display/ws`,
authenticated with the same per-node token every other Session-Agent
call uses) instead of the backend dialing a sandbox's VNC port directly
— `app/api/display.py`'s `display_ws()` keeps every existing check
(ownership, session status, Origin validation, real-time clipboard
filtering) completely unchanged and simply relays through a second,
per-node WebSocket instead of a raw TCP socket. The session-readiness
probe (`_wait_for_display_ready()`) moved the same way, onto a new
`GET /v1/sandboxes/{id}/display/ready` REST endpoint. The backend lost
its `browser-plane` network membership entirely; the Session Agent
gained it (a net narrowing of the control plane's own network
footprint, not just a like-for-like swap — see the ADR's Decision §4).
`browser-plane`'s subnet (`OPENRBI_BROWSER_PLANE_SUBNET`) and the
Session Agent's pinned relay address (`OPENRBI_AGENT_BROWSER_PLANE_IP`,
replacing the removed `OPENRBI_BACKEND_BROWSER_PLANE_IP` — a deliberate
breaking rename, see the ADR's Consequences) are both now per-deployment
overrides instead of hardcoded values.

**Verification caveat, stated plainly**: this phase's own Definition of
Done below calls for proving the relay round-trips through a genuinely
separate second host. That has **not** been done — everything here was
verified against the existing single-host `docker-compose` stack (a
second, independently-addressed Session Agent container standing in for
a second node, the same technique every earlier B2 phase's tests use),
including the full existing `test_display_websocket_origin.py` suite and
a real noVNC session end to end via the Admin/User Portals. The design
deliberately avoids any same-host assumption (no code path checks or
relies on IP adjacency between the control plane and a node), but that
remains a design claim, not a proven one, until it's exercised against
real separate hardware — tracked as an open item for Roadmap B2.6/B2.7,
where a real second-host deployment is first exercised at all.

**Goal**: Make the noVNC display path work when the sandbox is not on the
same Docker bridge as the backend, and give each node its own
non-colliding `browser-plane` subnet.

**Touches**: `backend/app/api/display.py`, `docker-compose.yml` (per-node
subnet becomes a documented per-deployment override, not a hardcoded
`172.30.0.0/24`), `session-agent/app/main.py` (gains a display-proxy
responsibility), `docs/architecture.md`'s trust-boundary diagram.

**Design direction**: the backend no longer dials a sandbox's VNC port
directly (it can't, once the sandbox is on another host's private bridge
network) — each node's own Session Agent proxies/relays its own sandboxes'
display traffic, and the backend's WebSocket terminates at *that* node's
relay instead. This keeps the existing invariant ("the client never gets a
direct route to a sandbox's VNC port") intact by moving the relay
endpoint, not by removing it.

**Definition of Done**:
- Each `BrowserNode`'s `browser-plane` subnet is a per-node config value
  (documented allocation scheme — e.g. `172.30.<node-index>.0/24` — to
  keep them trivially non-colliding).
- A session on a remote node's noVNC connection round-trips through that
  node's Session Agent, verified against a genuine two-host test
  deployment, not just two containers on one Docker host pretending to be
  separate hosts.
- `scripts/setup-network-isolation.sh` runs per-host with correct
  per-node `OPENRBI_BACKEND_BROWSER_PLANE_IP`-equivalent exemption, and
  the existing `/etc/openrbi/network-isolation` marker-file health check
  becomes a per-`BrowserNode` signal (the admin health view shows which
  nodes have verifiably applied isolation, not just the backend's own
  local marker).

**ADR required**: yes — `docs/adr/0024-cross-host-display-relay.md`,
recording the "relay moves to the node" decision and explicitly why the
client-never-reaches-sandbox-directly invariant still holds.

**Security scrutiny**: **high** — this phase changes the trust boundary of
the single most security-relevant data path in the product (the live
display of a remote-controlled browser). Review should confirm the
per-node relay enforces the same origin/auth checks `app/api/display.py`
already does today, not a weakened copy.

### B2.5 — Reconciliation & node-down handling — **done**

`orphan_reconciler.py` now walks every `APPROVED` node's own inventory
(via `connection_for_node()`, B2.2) instead of the single legacy default
agent. Both directions (container-with-no-row, row-with-no-container) are
scoped per node, and the per-cycle grace-period tracking dicts (shared
across nodes, since session ids are globally unique) are only touched for
sessions that actually belong to the node being reconciled that cycle —
one node's cycle can no longer clear another node's grace-period count.
A node whose agent is unreachable this cycle doesn't abort the whole
reconciliation run (one bad node never blocks reconciling the others,
same principle as `select_node()`); its forward (container-vs-row) check
is simply skipped for the cycle, and every one of its plausibly-active
sessions becomes a lost candidate for the reverse direction, since
liveness can't be confirmed — this is the "node goes OFFLINE mid-session"
case. No migration is attempted (sessions are sticky to their node,
B2.3); once past the grace period the session transitions to `FAILED`
(`SESSION_LOST_RECONCILED`, tagged `node_unreachable: true` to distinguish
it from the pre-existing single-container-vanished case) and becomes
eligible for forced termination — the best-effort `terminate_sandbox()`
cleanup call is skipped specifically for an unreachable node (it would
only ever fail while the node stays down, and would otherwise block the
session from ever reaching `FAILED`), but is still attempted normally
when the node answered this cycle and only that one cleanup call failed.
`download_poller.py` and `worker_health.py`/`dashboard.py` needed no
changes — both already iterate every `BrowserSession`/`BrowserNode` row
without a single-node assumption (`download_poller.py` already resolves
its own per-node connection via `app/services/downloads.py`, wired in
B2.2; `worker_health.py`/`dashboard.py` already `select(BrowserNode)`
with no node filtering, per their original B1.10.1 multi-node-shaped
design). Verified against the real docker-compose stack: the existing
single-node orphan-reconciliation suite passes unchanged, plus two new
tests (`test_orphan_reconciler_multinode.py`) proving a session on an
unreachable node reaches `FAILED` after the grace period with the right
audit metadata, and that reconciling a real session on a healthy node is
unaffected by another node being down in the very same cycles.

**Goal**: Orphan reconciliation and health computation iterate every
registered node, and a node going OFFLINE mid-session has a documented,
tested failure behavior.

**Touches**: `backend/app/core/orphan_reconciler.py`,
`backend/app/core/download_poller.py`, `backend/app/services/worker_health.py`
(already multi-node-shaped per its own design — extend, don't rewrite).

**Definition of Done**:
- `orphan_reconciler` walks every `APPROVED` node's inventory, not one.
- A node that goes OFFLINE mid-session: no migration attempted (documented
  explicitly, matching B2.3's stickiness statement); the session
  transitions to an admin-visible failure state and becomes eligible for
  forced termination — the exact sequence already proven single-node in
  `backend/tests/integration/test_orphan_reconciler.py` extended to the
  multi-node case.
- Dashboard/worker health correctly reflects an OFFLINE node's sessions as
  failed, not silently dropped from any count.

**ADR required**: no (extends existing, already-multi-node-aware health
logic).

### B2.6 — Deployment & ops — **done (single-host verified only)**

New `docker-compose.node.yml`: a standalone (not an overlay — a node host
has none of the control-plane services at all) compose file bringing up
just a Session Agent and its own local `browser-plane`. The Admin
Portal's Register/Approve/Revoke flow (built in B2.1) already satisfies
"no direct database access needed" — no frontend changes were required
for this phase. `docs/deployment.md` gained a "Multi-node" section
(marked experimental/technology preview, the same honesty pattern as
Segmented) with the full add/remove-a-node operator walkthrough, and its
`#sizing` section now covers N-node capacity as a sum of each node's own
`OPENRBI_AGENT_CAPACITY`.

Verified end to end on the real single-host stack (a second Session
Agent standing in for a second node, same technique every earlier B2
phase's tests use — genuine cross-host testing remains the open item
recorded in [ADR 0024](adr/0024-cross-host-display-relay.md)): using
`docker-compose.node.yml` itself (`docker compose -p openrbi-node2 -f
docker-compose.node.yml up -d`, connected to the primary stack's
`control-plane` network to reach it), the node self-enrolled, was
approved via the real `approve_node()` service function, was correctly
selected by the real `select_node()` once the default node was drained,
and a real sandbox was created, started, passed its VNC-readiness probe,
and was cleanly terminated on it — the actual DoD claim below, proven
rather than assumed. One real finding from this run: `session-agent`'s
`sandbox_network_name` default only matches `docker-compose.yml`'s
*default* Compose project name: evaluating a second node on the same
host as the primary stack (which needs a distinct `-p` project name to
avoid colliding with it) requires overriding
`OPENRBI_AGENT_SANDBOX_NETWORK_NAME` to match — documented in
`docker-compose.node.yml`'s own comments. A real second host, run with
the default project name, needs no such override.

**Goal**: A node host can run *just* a Session Agent + its own network
isolation, cleanly separate from the control-plane compose file.

**Touches**: a new `docker-compose.node.yml` (mirrors the existing
`docker-compose.segmented.yml` additive-overlay pattern), `docs/deployment.md`
(new "Multi-node" section, `#sizing` updated for N-node capacity planning),
`frontend/admin/src/pages/Workers.tsx` (a "Register node" flow — issue an
enrollment token, show pending approvals from B2.1).

**Definition of Done**:
- `docker compose -f docker-compose.node.yml up -d` on a second host,
  pointed at the control plane's admin-approval flow, results in a real
  second `BrowserNode` schedulable end to end.
- `docs/deployment.md` explicitly marks this "experimental / technology
  preview" until it has the same complete-production-guide treatment
  Compact has today — matching the existing honesty pattern used for
  Segmented, not overselling readiness.
- Admin Portal can register/approve/revoke a node without touching the
  database directly.

**ADR required**: no (deployment packaging, decisions already made in
earlier phases).

### B2.7 — Testing & fault injection — **done**

Both Definition of Done items below are now real, automated, CI-gated
scenarios (part of the existing `backend-integration-tests` job, which
already runs `run-integration-tests.sh` → `run-security-tests.sh` →
`run-fault-injection-tests.sh` in sequence on every PR):

- **`scripts/run-security-tests.sh`, new section 6**: enrolls a real
  rogue node against the live stack's own database via `enroll_node()`
  (the same service function the real, unauthenticated
  `POST /admin/nodes/enroll` endpoint calls after verifying a single-use
  token — this is the black-box regression the roadmap calls for,
  complementing B2.1's own unit-level `test_admin_nodes.py` coverage,
  not replacing it), confirms it lands `PENDING` with no `endpoint_url`,
  then calls the real `select_node()`/`create_session()` repeatedly and
  asserts the rogue node is never selected and never receives a
  session — proving [ADR 0023](adr/0023-node-enrollment-and-trust-model.md)'s
  central claim ("a leaked enrollment token is not, by itself,
  sufficient") against live infrastructure, not a throwaway pytest
  fixture DB.
- **`scripts/run-fault-injection-tests.sh`, new Fault 12**: brings up a
  real second node with `docker-compose.node.yml` (Roadmap B2.6,
  self-enrolling with a real single-use token, approved via the real
  `approve_node()`), seeds a real ACTIVE session onto it (draining the
  default node so `select_node()` is forced to place it there for real,
  not a hand-set `node_id`), then `docker kill`s that node's Session
  Agent outright — the same category of fault every other scenario in
  this script injects. Verifies all three Definition of Done claims:
  the killed node's session reaches `FAILED` with the B2.5
  `node_unreachable: true` tag, a survivor session on the default node
  is completely unaffected, and `select_node()` reschedules new sessions
  onto the survivor. `fault-injection-probe.py` gained the
  `node2-*` command family this scenario drives.

Both were verified locally against the real single-host stack before
being committed (same single-host-standing-in-for-a-second-node
technique as every earlier B2 phase, per [ADR 0024](adr/0024-cross-host-display-relay.md)'s
stated verification gap) — every assertion passed, including the killed
node deliberately leaving its own sandbox container behind (an
unreachable node's containers are the operator's concern once it's
reachable again, per B2.5's own documented design), which the cleanup
path in `run-fault-injection-tests.sh` now explicitly accounts for
rather than assuming `docker compose down` handles it.

**Goal**: Multi-node scenarios get the same fault-injection rigor
single-node already has.

**Touches**: `backend/tests/integration/test_worker_health.py`,
`test_admin_nodes.py` (multi-node fixtures), `scripts/fault-injection-probe.py`,
`docs/release/*-acceptance.md`-style acceptance docs.

**Definition of Done**:
- A fault-injection scenario: kill one of N nodes mid-session, verify
  sessions on the *other* nodes are unaffected, the killed node's sessions
  reach the B2.5 failure state, and new sessions schedule onto the
  survivors.
- A rogue/unapproved node attempting to receive scheduled sessions is
  covered by a security regression test (not just B2.1's unit-level
  check) — the same category of test `scripts/run-security-tests.sh`
  already runs for other host-level concerns.

**ADR required**: no.

## Suggested implementation order

B2.1 → B2.2 → B2.3 → B2.5 (can run in parallel with B2.4 once B2.2 lands,
since reconciliation doesn't strictly depend on the display-relay
redesign) → B2.4 → B2.6 → B2.7. B2.4 is called out as gating little else,
so it's fine for it to take the longest — everything except the actual
live-viewing session-agent-behind-a-real-second-host testing can be
validated with B2.1–B2.3 alone against two containers on one Docker host.

## What this roadmap deliberately does not cover

- Host-resource-aware auto-scaling of capacity (flagged in B2.3 as a
  follow-up, not silently dropped — see [Roadmap B3](roadmap-b3-capacity-autoscaling.md),
  which picks this up directly).
- Live session migration between nodes (explicitly out of scope,
  documented in B2.3/B2.5, not assumed away).
- Kubernetes/orchestration — stays out of scope per the project's existing
  non-goals (`README.md`), same as Segmented's Alternatives-Considered
  rejection of a Helm chart.
