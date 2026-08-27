# Fault-Injection / Reliability Acceptance

Status: **PASS**  
Last executed: 2026-08-27 (Fault 14 addition, Roadmap B3.4)  
Scope: isolated local Docker Compose test stack only

The authoritative executable is `scripts/run-fault-injection-tests.sh`. It is
also a required step of the `Backend integration tests` CI job. The script is
destructive by design and must never be pointed at production containers.

## Acceptance result

| Fault | DB / session state | Container / capacity | Audit / incident | Admin warning / user handling | Result |
|---|---|---|---|---|---|
| `docker kill` Browser Sandbox | `ACTIVE -> FAILED`, `ended_at` set | stopped container removed; live count returned to capacity | `SESSION_LOST_RECONCILED`; 0 incidents expected | `lost_sessions`; reconnect sees a terminal session | PASS |
| `docker kill` Session Agent | existing session stays `ACTIVE`; attempted new session creates no row | sandbox remains running; scheduling becomes unavailable, then returns to the same live/capacity count | no business audit or incident expected for an infrastructure process stop | aggregate health `DEGRADED`, agent/runtime/image `UNAVAILABLE`; new session gets explicit no-capacity error | PASS |
| `docker restart` Backend | session and user rows unchanged; Redis login retained | sandbox remains running; capacity refreshed from Agent | no synthetic audit/incident expected | liveness recovers and the existing authenticated state remains usable | PASS |
| `docker restart` PostgreSQL | persisted user/session/audit rows survive | sandbox remains running; capacity unchanged | existing audit remains queryable; no synthetic incident | DB readiness and application query recover; no ghost row | PASS |
| `docker restart` Redis/Valkey | browser and DB state unchanged | sandbox and capacity unchanged | no synthetic audit/incident | persisted server-side login token remains valid after controlled restart | PASS |
| stop ClamAV | quarantine row becomes `scanner=ERROR`, `status=QUARANTINED` | no file is released; worker capacity unaffected | `DOWNLOAD_BLOCKED`; no incident expected for scanner outage alone | health reports scanner unavailable; file stays unavailable to user | PASS |
| manually leave Browser container | no `BrowserSession` row exists | orphan removed after two-cycle grace; capacity restored | `ORPHAN_SESSION_RECONCILED`; 0 incidents expected | `orphan_sessions`; no user exists for the orphan | PASS |
| kill session during `STARTING` | `STARTING -> FAILED` | hard-killed/stopped container removed; no capacity leak | `SESSION_START_FAILED`; 0 incidents expected | `session_start_failures`; caller receives explicit startup error | PASS |
| Worker Drain | node round-trips `ONLINE -> DRAINING -> ONLINE`; existing session remains `ACTIVE` | existing container/capacity preserved; no new scheduling | enable/disable events; 0 incidents expected | `draining`; new session receives no-capacity error | PASS |
| Worker Maintenance | node round-trips `ONLINE -> MAINTENANCE -> ONLINE`; existing session remains `ACTIVE` | existing container/capacity preserved; no new scheduling | enable/disable events; 0 incidents expected | `maintenance`; new session receives no-capacity error | PASS |
| interrupt Agent control-plane network | no session row is created while runtime state is unknown; existing row stays `ACTIVE` | no scheduling on unknown capacity; state refreshes after deterministic Agent recreation | no business audit/incident expected because rejection precedes session creation | aggregate health `DEGRADED`; explicit no-capacity error | PASS |
| real host CPU pressure (Roadmap B3.2/B3.4) | no session row created while capacity is genuinely 0 | reported capacity drops to 0 (real cores pinned busy, not simulated), held on the very next poll after pressure clears (B3.2 hysteresis), recovers once sustained real headroom returns | no business audit/incident expected because rejection precedes session creation | Workers/Worker Detail show the real CPU-bound reason and raw numbers (Roadmap B3.3); explicit `NoCapacityError` | PASS |

An incident count of zero is an asserted result where listed, not an omitted
check. OpenRBI deliberately does not turn every transient infrastructure fault
or automatically reconciled session into an incident. Malware detection and an
administrator's explicit session isolation do create incidents and remain
covered by the security/integration suites.

## Reproduction

Prerequisites are the same isolated stack used by backend CI: generated
non-placeholder secrets, migrated PostgreSQL, the `openrbi-browser:latest`
image, and a Session Agent able to reach the test runner's Docker socket.

```sh
docker compose up -d --build
docker compose exec -T backend alembic upgrade head
docker build -t openrbi-browser:latest -f docker/browser/Dockerfile docker/browser
sh scripts/run-fault-injection-tests.sh
```

Expected terminal evidence:

```text
PASS: all destructive fault-injection acceptance scenarios recovered without ghost state or lost capacity
```

The probe prints a JSON observation for every fault, including DB/session and
container state, worker capacity, audit event, incident count, admin warning,
and user-facing error handling. Any missing or incorrect assertion exits
non-zero and fails the release gate.

## Reliability changes validated by this run

- Reconciliation now compares both running sandboxes and an all-managed
  inventory that includes `created`, `exited`, and `dead` containers. This
  closes the stopped-container blind spot exposed by a real `docker kill`.
- A lost active session is only finalized as `FAILED` after idempotent sandbox
  cleanup succeeds. Failed cleanup remains a retry candidate.
- A startup failure performs immediate best-effort cleanup and records
  `SESSION_START_FAILED`. Deferred cleanup remains discoverable through the
  all-managed inventory after the Agent recovers.
- Recent startup failures, lost sessions, and orphan cleanup are visible in
  the Admin Dashboard instead of requiring manual audit-log discovery.

## Evidence

- Local destructive run on 2026-08-15: all 11 scenarios PASS.
- Targeted live integration tests: `12 passed`; after adding the startup
  cleanup regression the reconciler file contains four real-Agent tests.
- CI evidence is the `Backend integration tests` job and its required parent
  `Release gates` check on the commit being released.
- Roadmap B3.4 (2026-08-27), Fault 14 real host CPU pressure and its
  fail-closed rejection, targeted local verification against the real
  live stack (the full script's `json_field` helper needs a host
  `python`, unavailable on this Windows dev machine — CI's Linux runner
  is the full script's authoritative run; targeted per-command
  verification, calling `fault-injection-probe.py` directly inside the
  real backend container, is the established pattern for local
  verification throughout this project, same as B3.2's own development):
  - `capacity-snapshot` before real pressure: `capacity=12, capacity_bound=ram`.
  - 16 real containers pinning every visible host core busy for 60s:
    `capacity=0, capacity_bound=cpu, cpu_capacity=0` within 6s.
  - `capacity-exhausted-rejects-session`: a real `create_session()` call
    raised `NoCapacityError` (`"no enrolled node is online with free
    capacity"`), with the session row count unchanged before/after —
    no ghost row.
  - Pressure cleared: capacity held at 0 for one more poll (B3.2
    hysteresis, not instantly back to full), then recovered to 11 within
    a few seconds.
  - Real Admin Portal, real logged-in browser session, live during the
    same pressure window: Workers page showed `CPU 100%`, `Sessions 0 /
    0`, health `DEGRADED`, and the real "CPU-bound" tag next to the
    session count (Roadmap B3.3) — not simulated or read from the API
    directly, read from the rendered page.
