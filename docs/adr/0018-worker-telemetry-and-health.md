# ADR 0018: Worker telemetry and a centrally-defined health model

## Status

Accepted

## Context

Roadmap B1.10 turns the Admin Portal into a real operations surface. Before this, `BrowserNode` (the codebase's existing name for what the task calls a "worker") had no CPU/RAM telemetry at all, its heartbeat only ever refreshed as a side effect of session creation or an admin loading the System page, and its `status` enum (`ONLINE/DRAINING/OFFLINE/DEGRADED`) was consulted directly by scheduling code (`select_node()`) with no single place defining what an admin-facing "is this worker healthy" label should mean.

## Decision

### Reuse `BrowserNode`, add columns — no second worker model

No new entity. `cpu_percent`, `ram_total_mb`, `ram_used_mb`, `node_started_at` are new nullable columns on the existing `browser_nodes` table (migration `b91a2d47e6c3`). Nullable because a node that has never successfully reported has none of this yet — never defaulted to `0`, which would misrepresent "no data" as "idle."

### Telemetry source: the Session Agent, host-wide

`session-agent/app/main.py`'s `GET /v1/nodes/self` (already the sole source of `BrowserNode` data) now also reports `cpu_percent` (`psutil.cpu_percent`), `ram_total_mb`/`ram_used_mb` (`psutil.virtual_memory`), and `node_started_at` (the Session Agent process's own start time). These are deliberately **host-wide**, not scoped to the Session Agent container's own cgroup: the browser sandboxes it manages are sibling containers on the same host, so host-wide load is what "how loaded is this worker" means to an operator, not just one process's footprint. `capacity` remains the pre-existing fixed placeholder (`10`) — real capacity-from-resources scheduling is out of scope for B1.10.1.

### Freshness: a poller, not just opportunistic refresh

`BrowserNode` was previously only refreshed by `select_node()` (on session creation). An idle system with no new sessions could show arbitrarily stale telemetry indefinitely. `app/core/node_poller.py` adds a fixed-interval refresh (`OPENRBI_NODE_POLL_INTERVAL_SECONDS`, default 15s — the project brief's own "a few seconds to a few tens of seconds" guidance), started from the FastAPI `lifespan` hook in an admin-capable listener, using the same in-process-`asyncio.Task` pattern already established by `app/core/download_poller.py` — no new background-worker infrastructure introduced. The poller's own exception handling never lets a transient Session Agent outage, or the table not existing yet during a not-yet-migrated startup (the exact class of bug B1.9's own lifespan hook hit in CI — see that fix's commit), crash the backend; a node simply stops advancing its heartbeat and the health model (below) reports it `OFFLINE` on its own.

The refresh logic itself was extracted from `select_node()` into `refresh_node_from_agent()` (`app/services/sessions.py`) so both the poller and real session scheduling share one implementation — never two.

### A single, centrally-defined health label — `app/services/worker_health.py`

`BrowserNode.status` remains the raw, admin-settable scheduling flag `select_node()` acts on directly (`ONLINE/DRAINING/OFFLINE/DEGRADED/MAINTENANCE`). A new, distinct computed label — `WorkerHealth`: `HEALTHY/DEGRADED/DRAINING/MAINTENANCE/OFFLINE` — is what every admin-facing surface (Workers list, worker detail, dashboard aggregates, System Health) reads instead of deriving its own notion of "healthy." `compute_worker_health()` is a pure function, evaluated in this order:

1. `MAINTENANCE` — an admin took the node out of service; wins over every other signal, including a stale heartbeat.
2. `OFFLINE` — heartbeat missing or older than `OPENRBI_NODE_HEARTBEAT_STALE_SECONDS` (default 45s, 3× the poll interval — tolerates one or two missed polls without flapping). Checked before `DRAINING`/`DEGRADED`: a stale row's own `status` field isn't trustworthy either.
3. `DRAINING` — admin-set, no new sessions, existing sessions continue.
4. `DEGRADED` — either self-reported by the Session Agent, or CPU/RAM at or above `OPENRBI_NODE_CPU_DEGRADED_PERCENT`/`OPENRBI_NODE_RAM_DEGRADED_PERCENT` (both default 90%).
5. `HEALTHY` — none of the above.

Backend is authoritative for this label; nothing in the frontend (B1.10.2/.3) re-derives it from raw fields.

### A new state: `MAINTENANCE`, distinct from `DRAINING`

`DRAINING` (unchanged): no new sessions, existing sessions keep running, is expected to reach zero sessions naturally. `MAINTENANCE` (new): the node is fully excluded from scheduling regardless of capacity — an intentional, explicit "don't consider this node at all" hold, for planned host-level work. Neither state's own transition terminates existing sessions on that node — session termination is a separate, explicit, auditable action (Roadmap B1.10.4), never an implicit side effect of a status change. `select_node()`'s heartbeat-refresh already had to protect `DRAINING` from being silently overwritten by the Session Agent's own always-`ONLINE` self-report; the same protection now covers `MAINTENANCE`.

### Audit: fixing a real gap, not just adding new events

`NODE_DRAINED` (the pre-existing event) is superseded by `WORKER_DRAIN_ENABLED` going forward — kept as a valid enum value (Postgres enums can't drop values) but no longer emitted. `WORKER_DRAIN_DISABLED` is new: `undrain_node()` previously recorded no audit event at all, an asymmetry this closes. `WORKER_MAINTENANCE_ENABLED`/`WORKER_MAINTENANCE_DISABLED` are new, mirroring the drain pair exactly.

## Alternatives Considered

- **A separate `worker_metrics`/telemetry table** instead of columns on `BrowserNode` — deferred to B1.10.2, which needs actual time-series history for the dashboard's graphs; B1.10.1 only needs the *current* reading, for which columns on the existing row are simplest and match every other "current state" field already on `BrowserNode`.
- **Container-scoped (cgroup) CPU/RAM instead of host-wide** — rejected: would only reflect the Session Agent process's own tiny footprint, not the sandboxes it's actually managing, defeating the purpose of a "worker load" indicator.
- **A cron/systemd-timer-driven poller instead of an in-process asyncio task** — rejected for the same reason `download_poller.py` chose the same pattern: no existing scheduled-job infrastructure to hook into, and a single-backend-process MVP has no coordination problem to solve yet.
- **Renaming `BrowserNodeStatus.ONLINE` to `HEALTHY` directly** — rejected: would be an invasive, purely cosmetic rename touching scheduling code, existing tests, and stored data for no functional gain, when a separate computed label achieves the same admin-facing vocabulary without touching what `select_node()` already correctly keys on.

## Consequences

Adds one migration (four new columns, one new `BrowserNodeStatus` value, four new `SecurityEventType` values), one new service module (`worker_health.py`), one new background task (`node_poller.py`), two new admin endpoints (`POST /admin/nodes/{id}/maintenance`, `.../unmaintenance`), and extends `BrowserNodeResponse` with `health`, `cpu_percent`, `ram_total_mb`, `ram_used_mb`, `uptime_seconds`. No frontend surface yet — the Workers list/detail UI upgrade to actually display any of this is Roadmap B1.10.3, tracked separately.
