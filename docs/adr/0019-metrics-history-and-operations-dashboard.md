# ADR 0019: Metrics history and the Operations Dashboard

## Status

Accepted

## Context

Roadmap B1.10.1 ([ADR 0018](0018-worker-telemetry-and-health.md)) gave `BrowserNode` real *current* CPU/RAM telemetry and a centrally-defined health label, but no history — every prior reading was overwritten in place. B1.10.2 needs to answer "what did session load look like over the last hour/day/week", which requires keeping samples over time, and the Admin Portal's `Dashboard.tsx` had no dedicated backend endpoint at all: it aggregated `listSessions()`/`listIncidents()`/`listQuarantine()`/`getHealth()` client-side, which doesn't scale and can't show a graph.

## Decision

### A small metrics-history table, not a time-series database

`WorkerMetricSample` (migration `c72f8e1a94d5`): one row per worker per poll tick (`node_id`, `recorded_at`, `cpu_percent`, `ram_used_mb`, `ram_total_mb`, `active_sessions`), written by `app/core/node_poller.py` right after each `refresh_node_from_agent()` call — the same 15s cadence B1.10.1 already established, no second poller. Pruned to `OPENRBI_METRICS_RETENTION_DAYS` (default 7) at insert time in `metrics_history.record_sample()`. This is deliberately not a general-purpose time-series store (no Prometheus/Grafana, per the task's own MVP guidance) — it exists to serve exactly two things: the dashboard's aggregate session-history graph now, and per-worker CPU/RAM graphs in B1.10.3 later, from the same table.

### Time-bucketing with Postgres `date_bin()`, scoped per range

A 7-day range at a 15s sample rate is ~40,000 raw rows — too many points for a chart or a JSON response. `metrics_history.session_history()` uses Postgres's `date_bin()` to bucket into a fixed point count per range (`RANGE_CONFIG`): 1h→1min buckets (~60 points), 6h→5min (~72), 24h→15min (~96), 7d→1h (~168). Buckets average `active_sessions` per `(bucket, node_id)` first, then sum across nodes per bucket, so a multi-worker deployment's graph reflects total session load, not one arbitrarily-picked node.

### `app/services/dashboard.py` — aggregation lives in one service, not the route

`GET /admin/dashboard` (`app/api/admin_dashboard.py`, same `require_role("ADMIN", "SECURITY_REVIEWER")` dependency as the existing nodes/health routes) delegates entirely to `get_dashboard()`. It computes: active session count (same `ACTIVE`/`DISCONNECTED` definition the old client-side `Dashboard.tsx` used, kept consistent rather than silently redefined); per-worker health via B1.10.1's `compute_worker_health()` (computed once per node, cached, never re-derived twice in the same request); avg CPU/RAM across nodes that have reported telemetry (nodes with none are excluded from the average, never averaged in as `0` — a fleet with one brand-new, not-yet-reporting node must not show a falsely low average); system health via the existing `get_system_health()` (no second health check); warnings (sustained high CPU — all samples in the last 10 minutes at/above the degraded threshold, to avoid flagging a single noisy sample; draining/maintenance/offline nodes; ≥3 failed logins per username in the last 15 minutes, read from existing `USER_LOGIN_FAILED` security events — no new surveillance, no new event type); and the bucketed `session_history`.

### Never fabricate a number

`active_sessions_delta_last_hour` is `null`, not `0`, when there isn't yet an hour of real session history to compare against (a fresh install, or a worker that just started) — a `0` there would claim "no change" when the true answer is "no data yet," which is exactly the kind of vanity-dashboard behavior the task's brief explicitly rules out.

### Frontend: hand-rolled SVG chart, no new dependency

No charting library exists anywhere in the frontend (checked). `frontend/shared/components/LineChart.tsx` is a small SVG line chart handling its own loading/empty/error states, with hover tooltips and up to ~6 evenly-spaced axis labels regardless of point count — consistent with the codebase's existing hand-rolled `Icons.tsx` precedent rather than adding a dependency for a handful of charts.

### Polling, not WebSocket/SSE

`Dashboard.tsx` polls `GET /admin/dashboard` every 15s (matching the poller's own cadence) and shows a visible "Last updated HH:MM:SS" clock plus a "Telemetry delayed" badge driven by the response's own `telemetry_stale` field (true when any worker's heartbeat is stale) — per the task's own "robust polling is entirely acceptable for MVP" guidance, so stale data is always visibly marked, never silently shown as current.

### No dark mode added

No dark-mode implementation exists anywhere in the frontend today (checked across all of `frontend/shared`, `frontend/admin`, `frontend/user`). The new chart/load-bar/warning CSS is built purely from existing design tokens and does not introduce a partial dark theme — a half-dark dashboard while the rest of the product stays light-only would be a worse inconsistency than staying uniform. Tracked as a known limitation, not silently dropped.

## Alternatives Considered

- **Prometheus + Grafana** — rejected for MVP: real operational overhead (a second stack to deploy/secure/back up) for a feature whose actual retention need (7 days, ~168 chart points at the coarsest range) a small internal table already satisfies.
- **Storing every raw sample forever** — rejected: unbounded growth for data whose usefulness decays after the retention window; pruned at insert time instead of a separate cleanup job, keeping the write path self-contained.
- **WebSocket/SSE push instead of polling** — rejected for MVP per the task's own explicit guidance; polling is simpler to reason about, and a 15s interval is already the data's own real refresh rate, so push would not show anything sooner.
- **A `0` default for CPU/RAM averages and the session delta when data is missing** — rejected throughout; every "unknown" case surfaces as `null`/an explicit empty state in the API and UI rather than a fabricated number that looks like a real reading.

## Consequences

Adds one migration (`worker_metric_samples` table, indexed on `node_id` and `recorded_at`), one new service module each for bucketed history (`metrics_history.py`) and dashboard aggregation (`dashboard.py`), one new endpoint (`GET /admin/dashboard?range=1h|6h|24h|7d`), and one new frontend component (`LineChart.tsx`) reused by both the dashboard now and B1.10.3's per-worker graphs later. `Dashboard.tsx` is rewritten to consume the new endpoint instead of client-side aggregation; its "Recent security events" panel is kept as-is (still a real, cheap, useful view). No new background task — reuses B1.10.1's existing poller.
