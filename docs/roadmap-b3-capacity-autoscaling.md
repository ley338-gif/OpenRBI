# Roadmap B3: Host-Resource-Aware Capacity Auto-Sizing

> Produced from direct repository analysis (`session-agent/app/main.py`,
> `session-agent/app/config.py`, `backend/app/services/sessions.py`,
> `backend/app/services/worker_health.py`, `backend/app/models/browser_node.py`)
> rather than a separate planning-brief document — the gap this roadmap
> closes was flagged explicitly as a tracked, not-silently-dropped
> follow-up in [Roadmap B2](roadmap-b2-multinode.md)'s "what this roadmap
> deliberately does not cover" section, and the codebase already collects
> everything this roadmap needs (host-wide `cpu_percent`/`ram_total_mb`/
> `ram_used_mb`, Roadmap B1.10.1) — there's no open design question this
> roadmap needs a separate brief to resolve first.
>
> **Status: roadmap only, nothing below is implemented.** Matches this
> project's existing convention (see Roadmap B2's own header) of
> separating "what should we do" from "doing it."

## Goal

Replace `OPENRBI_AGENT_CAPACITY` — a single fixed number an operator sets
once and the platform never revisits — with a capacity that reflects a
node's *actual, current* free host headroom, without relaxing any of the
Master-Auftrag's non-negotiables (fail-closed on any scheduler/agent
failure, no security decision in the frontend, still no host-resource
data trusted from anywhere other than the node's own agent).

The problem today: `_capacity_from_settings()` (`session-agent/app/main.py`)
returns a static integer regardless of what's actually running on the
host. An operator either sets it conservatively (wastes real, available
capacity most of the time) or optimistically (the host can be driven into
real memory/CPU pressure by sandboxes that never individually exceeded
their own `default_cpu_limit`/`default_ram_limit_mb`, simply because too
many of them are running at once). `compute_worker_health()`
(`backend/app/services/worker_health.py`) already flags a node `DEGRADED`
above `node_cpu_percent`/`node_ram_degraded_percent` (default 90%), but
that's purely a dashboard label today — `select_node()` (Roadmap B2.3)
never reads it, so a `DEGRADED` node keeps receiving new sessions exactly
like a healthy one.

## Open design decisions (recommended, not silently assumed)

| Decision | Recommendation | Why |
|---|---|---|
| What "capacity" means | **Reservation-based**: `capacity = floor(free host headroom / per-sandbox reservation)`, using the *existing* `default_cpu_limit`/`default_ram_limit_mb` as the reservation unit (whichever resource is scarcer wins) | Reuses a value the platform already enforces per sandbox (Docker's own `--cpus`/`--memory`) instead of inventing a second, competing notion of "how big is a sandbox." No new config concept for the operator to learn. |
| Where the computation happens | **Session Agent**, not the backend | `session-agent/app/main.py`'s `/v1/nodes/self` already self-reports `cpu_percent`/`ram_total_mb`/`ram_used_mb` — it already has the host-wide numbers this needs, and it's the same place `_capacity_from_settings()` already lives. The backend's role stays exactly what B2.3 already made it: trust whatever `capacity` the node reports, same as today. |
| Operator control | `OPENRBI_AGENT_CAPACITY` becomes a **ceiling**, not the only source of truth — the reported capacity is `min(computed_from_headroom, that ceiling)` (default ceiling unbounded, i.e. today's behavior is unchanged until an operator or the computed value opts in) | An operator may have real reasons to cap lower than the host physically allows (cost, noisy-neighbor policy, contractual limits) — auto-sizing should never override a deliberate operator ceiling, only ever tighten within it. |
| Reaction speed | **Smoothed, not instantaneous** — computed off the same periodic self-report cycle already polled by `node_poller.py` (`OPENRBI_NODE_POLL_INTERVAL_SECONDS`, default 15s), with a minimum-hold window before capacity is allowed to *increase* again after a drop | A capacity number that flaps every poll cycle makes `select_node()`'s least-loaded scoring (B2.3) unstable and could bounce sessions between nodes needlessly. Dropping capacity fast (protects the host) but raising it slowly (avoids thrashing back into the same pressure) is the standard asymmetric-hysteresis shape for this kind of control loop. |

## Phases

### B3.1 — Real per-node dynamic capacity computation — **done**

`_capacity_from_settings()` is now `_compute_capacity()`
(`session-agent/app/main.py`) — real capacity derived from actual free
CPU/RAM headroom at the instant `GET /v1/nodes/self` is called, using
`default_ram_limit_mb`/`default_cpu_limit` (the same per-sandbox
reservation Docker itself already enforces) as the unit; whichever
resource is scarcer wins. `OPENRBI_AGENT_CAPACITY` (`capacity` in
`session-agent/app/config.py`) is now a *ceiling* on that computed value
— `None` by default (uncapped), so an un-overridden node reports the
real computed number, not a flat 10; setting it caps the result but
never raises it above real headroom. A new `OPENRBI_AGENT_RESERVED_RAM_MB`
(default 512) is held back from the computation for the host OS/Docker
daemon/this agent process itself. Every host reading is passed into
`_compute_capacity()` as a plain argument rather than read via a live
`psutil` call inside the function, keeping it pure and deterministic for
`session-agent/tests/test_capacity.py` — the Session Agent's first pytest
suite, now run in CI (`.github/workflows/ci.yml`'s `python-quality` job)
alongside its existing ruff/mypy checks.

**Real-world interaction found while verifying this**: the backend's own
integration-test suite relies on a session-scoped cleanup fixture
(`tests/conftest.py`) that sweeps up DB rows once at the very end of a
run rather than terminating each session's real sandbox container
immediately — a deliberate, already-documented tradeoff (see ADR 0021).
Under the old flat `capacity=10`, the real containers this leaves running
mid-suite never mattered; under real headroom-based capacity, this
genuinely exhausted a real GitHub Actions runner's own free RAM,
confirmed by an actual CI run — not just a theoretical concern.
`OPENRBI_AGENT_CAPACITY=20` alone (`scripts/run-fresh-install-acceptance.sh`,
`scripts/run-backup-restore-acceptance.sh`,
`scripts/run-upgrade-acceptance.sh`, and every `.env`-generating step in
`.github/workflows/ci.yml`) turned out to be insufficient by itself — a
ceiling can only ever *lower* an already-higher computed value, so it
does nothing when the computed value itself is the binding constraint.
The same four places also now set `OPENRBI_AGENT_DEFAULT_RAM_LIMIT_MB=1024`
— shrinking the per-sandbox reservation the RAM computation divides by,
which both raises computed capacity *and* reduces what each test sandbox
actually uses. That alone still wasn't enough — a second real CI run
failed identically, revealing CPU, not RAM, as the actual binding
constraint on that runner (`default_cpu_limit=2.0`'s 200%-per-sandbox
divisor is large against a real runner's host-wide CPU load from
Postgres/Redis/ClamAV/the browser image build/Docker itself all running
concurrently). The same four places now also set
`OPENRBI_AGENT_DEFAULT_CPU_LIMIT=0.5`. Verified both changes together
don't just move the failure elsewhere: 1024 MB / 0.5 vCPU is still
enough for a real, working Firefox+Xvfb+x11vnc sandbox in the existing
noVNC/canvas E2E test, run locally against the real stack with both
settings applied.

**Goal**: `_capacity_from_settings()` stops being a flat number and
reflects actual free host headroom, bounded by the existing
`OPENRBI_AGENT_CAPACITY` as an optional ceiling.

**Touches**: `session-agent/app/main.py` (`_capacity_from_settings()` →
takes live `psutil` readings, not just `settings`), `session-agent/app/config.py`
(`capacity` becomes `capacity_ceiling: int | None`, default `None` =
uncapped; a **reserved headroom** setting for the host OS/Docker daemon
itself, e.g. `OPENRBI_AGENT_RESERVED_RAM_MB`, so sandboxes are never sized
to consume literally 100% of host RAM).

**Definition of Done**:
- `GET /v1/nodes/self`'s `capacity` field is computed from
  `(host_total_ram_mb - reserved_ram_mb - currently_used_ram_mb) /
  default_ram_limit_mb`, floored, clamped to `>= 0`, and clamped to
  `<= capacity_ceiling` when one is set.
- CPU is evaluated the same way (available cores × 100 − current
  `cpu_percent` load, divided by `default_cpu_limit`) and the **lower** of
  the RAM-derived and CPU-derived numbers wins — whichever resource is
  actually scarce on that host.
- A node with `OPENRBI_AGENT_CAPACITY` unset behaves exactly as this
  phase intends (computed); a node with it set behaves exactly as it does
  today if the computed value would exceed the ceiling, so **no existing
  single-node or multi-node deployment changes behavior on upgrade unless
  the operator's own ceiling is looser than their real headroom** —
  documented explicitly, not assumed.
- Integration test: a host reporting synthetic high RAM usage (mocked
  `psutil` reading, not a real memory-pressure test — see B3.4 for the
  real one) produces a correspondingly lower `capacity`, verified through
  a real `GET /v1/nodes/self` call against the real running agent.

**ADR required**: no — mechanical, confined to `_capacity_from_settings()`
and its inputs; no new trust boundary (the backend already trusts
whatever `capacity` a node self-reports, unchanged since B1.10.1).

### B3.2 — Smoothing and starvation guards — **done**

`session-agent/app/main.py` gained `_CapacityHysteresis`: a small
stateful wrapper around B3.1's pure `_compute_capacity()`. A drop
applies on the very next `GET /v1/nodes/self` call (fail-closed toward
safety — a real resource crunch is never hidden behind smoothing); a
rise only applies once `OPENRBI_AGENT_CAPACITY_RECOVERY_POLLS`
(`capacity_recovery_polls` in `session-agent/app/config.py`, default 3)
*consecutive* calls all sustain the higher value — any call in between
that drops back down resets the streak, since that's no longer a
sustained recovery. `OPENRBI_AGENT_RESERVED_RAM_MB`'s non-zero default
(512, from B3.1) already satisfied this phase's starvation-guard
requirement.

Verified with 6 new deterministic unit tests
(`session-agent/tests/test_capacity_hysteresis.py`, each constructing
its own fresh `_CapacityHysteresis` instance) and a real fault-injection
scenario (`scripts/run-fault-injection-tests.sh`'s new Fault 14,
`scripts/fault-injection-probe.py`'s new `capacity-snapshot` command).

Fault 14 originally drove real RAM pressure (a container committing and
touching ~1.2 GB of host RAM). A real CI run on PR #114 showed this was
unsafe: on an already memory-tight GitHub-hosted runner (already tuned
down for B3.1's own CI fix, see below), the extra ~1.2 GB pushed the
runner into genuine host memory exhaustion severe enough to break the
*backend's own* PostgreSQL connection pool
(`asyncpg.exceptions._base.InterfaceError: connection is closed`)
seconds after the fault started — an unrelated service casualty, not a
finding about capacity computation. Fault 14 was redesigned to drive
real CPU pressure instead (containers pinning every visible host core
busy for a bounded duration): CPU contention degrades throughput, not
availability, so it can't OOM-kill an unrelated container the way an
uncontrolled RAM commitment can.

Switching to CPU pressure surfaced a real, independent bug in B3.1's
own `_compute_capacity()`: `psutil.cpu_percent(interval=None)` (no
`percpu=True`) already returns a 0-100 *average* across every core, not
a value scaled by `cpu_count` — so the original
`cpu_count * 100 - cpu_percent` barely reacted to real load on any host
with more than one core (fixed to
`cpu_count * (100 - cpu_percent)`, with a new regression test,
`test_cpu_percent_is_treated_as_a_host_wide_average_not_a_flat_subtraction`,
covering an 8-core host at 90% average load that the old formula would
have under-reported as having room for 3 more sandboxes). This means
`_compute_capacity()`'s CPU-derived capacity was silently wrong on
every real multi-core host from the moment B3.1 merged until this fix —
caught only because Fault 14 needed a real CPU-bound scenario to pass,
not by the original unit tests (their CPU-bound scenario's expected
value happened to be numerically identical under both the buggy and
the corrected formula).

Confirmed live against the real stack after the fix: Fault 14 drives
real capacity down under real CPU pressure, confirmed still held on the
very next poll after the pressure containers are removed (not instantly
back to full — the exact DoD wording), then confirmed to eventually
recover. Observed live via repeated manual polling during development
(capacity `12 → 0` under pressure from 16 cores pinned busy, held at
`0` for one more poll after clearing it, recovered to `11` shortly
after).

A real CI run with a temporary diagnostic (polling `/v1/nodes/self`
every 2s during the actual test run and logging every reading) then
surfaced a second, independent bug: reported `capacity` oscillated
wildly poll to poll (e.g. `12 → 5 → 2 → 0 → 12` inside seconds) even
though real sustained load wasn't changing nearly that fast.
`psutil.cpu_percent(interval=None)` measures the delta since psutil's
*previous* call, process-wide — and `/v1/nodes/self` is polled
concurrently and rapidly from several callers (`node_poller.py`,
`select_node()` on every session creation, admin dashboard refreshes),
so that interval can shrink to a few milliseconds, and a momentary
blip in that tiny window reads as a misleading near-100% spike. Fixed
by switching to a fixed `interval=0.1` blocking measurement (immune to
caller timing entirely), run via `asyncio.to_thread` so one status
check can't stall the event loop for others; the now-unnecessary
import-time warm-up call (Roadmap B1.10.1) was removed along with it.
Confirmed live: firing 20 concurrent rapid requests during real CPU
pressure converges to a stable, consistent reading instead of
oscillating between near-0 and near-max on adjacent polls.

**Goal**: A momentary host spike doesn't cause `select_node()` (B2.3) to
see capacity oscillate every poll cycle, and the host OS/Docker daemon
itself is never starved by sandboxes filling every last reservable slot.

**Touches**: `session-agent/app/main.py` (capacity computation gains a
small rolling window / hold-down timer), `docs/architecture.md`'s
multi-node-readiness section.

**Definition of Done**:
- Capacity is allowed to **drop** on the very next poll (fail-closed
  toward safety), but only allowed to **rise** again after N consecutive
  polls (`OPENRBI_AGENT_CAPACITY_RECOVERY_POLLS`, a small default like 3)
  report sustained headroom — asymmetric by design, matching the
  Decisions table above.
- `OPENRBI_AGENT_RESERVED_RAM_MB` (B3.1) has a real, non-zero, documented
  default (not `0`, which would let sandboxes contend directly with the
  Session Agent process and the Docker daemon itself for the last MB of
  RAM) — a conservative starting value plus explicit deployment-doc
  guidance on tuning it per host.
- A fault-injection scenario (extending `scripts/fault-injection-probe.py`/
  `run-fault-injection-tests.sh`, matching Roadmap B2.7's own pattern):
  drive real host resource pressure and confirm reported capacity drops,
  `select_node()` respects the lower number, and it isn't already back
  at full capacity the moment the pressure clears. Implemented as real
  CPU pressure (pinning host cores busy), not RAM pressure — an
  uncontrolled real RAM commitment was found, via a real CI incident, to
  risk OOM-killing unrelated services on an already memory-tight runner;
  CPU contention degrades throughput without that blast radius. See the
  as-built notes above.

**ADR required**: no.

### B3.3 — Admin visibility into *why* capacity changed — done

**Goal**: An operator looking at a node whose capacity dropped can see
*why* (RAM- vs CPU-bound, current headroom numbers), not just a smaller
integer with no explanation.

**Touches**: `backend/app/api/schemas/nodes.py`/`admin_nodes.py`
(surface the RAM- vs CPU-derived breakdown, not just the final number),
`frontend/admin/src/pages/Workers.tsx`/`WorkerDetail.tsx` (show the
breakdown alongside the existing CPU/RAM history charts from Roadmap
B1.10.2/B1.10.3), `backend/app/services/dashboard.py` (a `capacity_bound`
warning kind, analogous to the existing `draining`/`maintenance`/
`lost_sessions` warning kinds, when a node is currently capped below its
`OPENRBI_AGENT_CAPACITY` ceiling by real headroom rather than by an
admin action).

**Definition of Done**:
- Workers page / Worker Detail shows, for a capacity-constrained node,
  which resource (CPU or RAM) is the binding constraint and the raw
  numbers behind it — not just "6/10".
- Dashboard's Needs Attention section surfaces a node that's been
  capacity-constrained by real headroom (not an admin action) for longer
  than a configurable threshold, the same way it already surfaces other
  node-health concerns.
- No new write path — this phase is read-only surfacing of data B3.1/B3.2
  already compute and report.

**ADR required**: no.

**As-built**: `_compute_capacity()` (session-agent/app/main.py) now
returns a `CapacityBreakdown` (capacity, ram_capacity, cpu_capacity,
`bound`) instead of a bare int — `bound` is `"ram"`/`"cpu"` (whichever is
strictly binding, ties going to `"ram"` deterministically) or
`"ceiling"` when `settings.capacity` is what's actually capping the
result below real headroom. `/v1/nodes/self` gained `capacity_bound`/
`ram_capacity`/`cpu_capacity` fields — deliberately *not* run through
B3.2's hysteresis (that's purely for the scheduling-critical `capacity`
number; the breakdown is informational and always reflects the current
instant). `BrowserNode` and `WorkerMetricSample` both gained matching
columns (migration `e3b3b0f8f6bd`), populated the same place `capacity`
itself already is (`_apply_node_status()`, `record_sample()`).
`BrowserNodeResponse` exposes the breakdown; Workers page shows a
"RAM-bound"/"CPU-bound" tag next to the sessions count (never for
`"ceiling"` — that's a deliberate admin config choice), Worker Detail
shows a full "Capacity limited by" line with both raw numbers. A new
`_capacity_bound_warnings()` (dashboard.py) mirrors the existing
sustained-high-CPU check's shape — every sample in a configurable
window (`OPENRBI_CAPACITY_BOUND_WARNING_MINUTES`, default 10) must show
`"ram"`/`"cpu"` for the warning to fire, never `"ceiling"`. Verified
against the real live stack: a real node's own capacity breakdown
(`ram_capacity=9, cpu_capacity=32, bound="ram"`), the dashboard warning
firing for 3 real sustained `"cpu"`-bound samples and staying silent for
3 real sustained `"ceiling"`-bound ones, and both the Workers table and
Worker Detail page rendering the breakdown correctly in a real logged-in
browser session. 9 new backend tests, 2 new session-agent unit tests.

### B3.4 — Documentation & real acceptance evidence

**Goal**: `docs/deployment.md#sizing` stops describing a fixed-ceiling
model and documents the real auto-sizing behavior; the Definition of Done
claims above get one consolidated, genuinely-run acceptance pass.

**Touches**: `docs/deployment.md#sizing`, `docs/roadmap-b2-multinode.md`
(update the "what B2 deliberately does not cover" note to point here now
that it's addressed), a new `docs/release/*-acceptance.md`-style scenario
or an extension of an existing one.

**Definition of Done**:
- `docs/deployment.md#sizing` explains the reservation model, the
  reserved-headroom setting, and how to still pin an explicit ceiling for
  operators who want the old fixed-number behavior back.
- One consolidated acceptance run: real memory pressure on a real host,
  capacity visibly drops in the Admin Portal, a session correctly fails
  closed with `NoCapacityError` when genuinely no headroom remains (not a
  silently-oversubscribed host), and capacity recovers once pressure
  clears — end to end, not simulated at the unit level.

**ADR required**: no.

## Suggested implementation order

B3.1 → B3.2 → B3.3 → B3.4, strictly sequential — each phase's Definition
of Done depends on the computation the previous phase introduced. Unlike
Roadmap B2, there's no natural parallel track here: this is a single,
narrow seam (one function's return value and what feeds it), not a
cross-cutting change touching many independent subsystems.

## What this roadmap deliberately does not cover

- **Per-sandbox dynamic resource limits** (shrinking/growing an
  individual running sandbox's own `--cpus`/`--memory` based on load) —
  out of scope. This roadmap only changes *how many* sandboxes a node
  will accept, never what any single sandbox is allowed to consume.
- **Cross-node capacity rebalancing / live migration** — still explicitly
  out of scope per Roadmap B2.3/B2.5's own stated position; a node's
  capacity number affects only new scheduling decisions, never existing
  sessions.
- **Non-Docker resource accounting** (e.g. GPU, disk I/O bandwidth) —
  the reservation model here is CPU/RAM only, matching what
  `SandboxConfig` already limits today (`cpu_limit`, `ram_limit_mb`,
  `pid_limit`, `disk_limit_mb`) — disk and PID limits are not part of the
  capacity computation itself in this roadmap, since neither is generally
  the binding constraint on a browser-sandbox host; a future phase could
  extend the same reservation model to either if real deployments show
  otherwise.
