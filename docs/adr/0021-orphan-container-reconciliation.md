# ADR 0021: Orphan-Container Reconciliation

## Status

Accepted

## Context

`GET /v1/nodes/self`'s `active_sessions` (`session-agent/app/main.py`) counts real, running Docker containers carrying the `openrbi.managed=true` label — entirely independent of the `browser_sessions` table's state. Diagnosis on the running dev stack found exactly this divergence: two containers (`openrbi-session-77b48f41-...`, `openrbi-session-8dd3f974-...`) running for 34–57 minutes with **zero** matching rows in `browser_sessions` (the table was completely empty). A near-identical incident is already recorded in `CHANGELOG.md` ("cleaned up ~11 orphaned sandbox containers accumulated from today's manual testing").

Root cause, confirmed by reading the actual test code rather than guessing among the candidates: `backend/tests/integration/test_policy_engine.py::test_create_session_applies_resolved_policy_resolution` calls `app/services/sessions.create_session()` directly — which really creates a Docker container through the Session Agent — and never calls `terminate_session()` before the test ends. `backend/tests/conftest.py`'s session-scoped, autouse `_cleanup_test_data` fixture then issues a raw `DELETE FROM browser_sessions WHERE user_id IN (...)` for every `pytest_`-prefixed user at the end of the whole test session, which removes the DB row without ever invoking the real terminate path (`session_agent_client.terminate_sandbox()`). The container is left running with no DB row at all — exactly the "Fall C" case (container exists, no `BrowserSession` row) described in the task brief, reproduced twice in the same dev stack from two separate manual test runs.

The test itself is not being fixed here as a workaround-of-convenience — a similar gap could reappear from a different test, a crashed process mid-`create_session()`, or a genuine but rare `terminate_session()` failure that leaves the row `FAILED` while the container is still up. The system needs to detect and correct this class of drift on an ongoing basis, not just patch the one reproduction.

## Decision

Add `app/core/orphan_reconciler.py`, an in-process periodic job (same pattern as `app/core/node_poller.py`/`download_poller.py` — see `docs/architecture.md`'s documented single-process deviation from the original multi-worker sketch), started/stopped from `app/main.py`'s lifespan alongside `node_poller`, gated by the same `listener_mode in ("admin", "both")` condition.

Each cycle (`OPENRBI_ORPHAN_RECONCILE_INTERVAL_SECONDS`, default 300s):

1. Fetch the live list of running `openrbi.managed` session IDs from the Session Agent via a new minimal endpoint, `GET /v1/sandboxes` (session-agent) → `list_active_sandboxes()` (backend client). This is a **new, separate** call from `count_active_sessions()`/`GET /v1/nodes/self`'s `active_sessions` int — that existing contract is untouched; `SandboxProvider` gets a new `list_active_session_ids()` method alongside it.
2. For every reported session ID, look up the `BrowserSession` row. A row in `QUEUED`/`STARTING`/`ACTIVE`/`DISCONNECTED`/`ISOLATING`/`ISOLATED`/`TERMINATING` means the container is legitimate (`TERMINATING` included: it's already mid-teardown via the real path, not orphaned). Anything else — no row at all, or a row in `TERMINATED`/`FAILED` — is a reconciliation candidate.
3. **Grace period**: a candidate is only acted on once seen on `OPENRBI_ORPHAN_RECONCILE_GRACE_CYCLES` (default 2) *consecutive* cycles, tracked in an in-process dict keyed by session ID. This exists specifically to avoid tearing down a session that's between its DB row being flushed (`db.add(session); await db.flush()` in `create_session()`) and the container actually existing — a real but narrow race, not a hypothetical.
4. A confirmed orphan is terminated through `session_agent_client.terminate_sandbox()` — the same `SandboxProvider.terminate_session()` path every other termination uses, never a direct Docker call — and a new `SecurityEventType.ORPHAN_SESSION_RECONCILED` event is recorded (`session_id`/`reason` in metadata; the DB `session_id` FK is populated only when a real row exists, since Fall C has none to reference).
5. **Fail closed**: if the Session Agent call itself fails, the whole cycle is skipped — never act on a partial or unknown view of what's actually running. The grace-period state is left untouched across a skipped cycle so a genuine orphan already mid-grace-period isn't reset by one transient outage.
6. Surfaced to admins proactively: `app/services/dashboard.py`'s existing `warnings` list (`GET /admin/dashboard`, B1.10.2) gets a new `orphan_sessions` warning when any `ORPHAN_SESSION_RECONCILED` event occurred in the last 24h — an admin sees this without having to go looking in the audit log first.

The underlying test hygiene gap (a real session created without a matching terminate, DB row deleted via raw SQL instead of the service path) is a separate, smaller fix tracked independently — this reconciler is the durable safety net regardless of which specific test or code path produces the next orphan.

## Alternatives Considered

- **Fix only the specific test / cleanup fixture** — necessary but insufficient on its own: it addresses this one reproduction, not the general class of drift (crashed processes, a `FAILED`-but-still-running edge case, future tests with the same bug).
- **Delete on first sighting, no grace period** — rejected: a session between `db.flush()` and the container actually starting would be a false positive, and killing a session mid-creation is a worse failure mode than leaving a genuine orphan running a few extra minutes.
- **Have the reconciler call Docker directly** — rejected outright: the backend must never touch the Docker socket (`docs/adr/0005-no-docker-socket-in-backend.md`); everything here goes through the Session Agent, same as every other sandbox lifecycle action.
- **A separate worker process instead of an in-process task** — rejected for MVP 1 for the same reason `node_poller`/`download_poller` are in-process (`docs/architecture.md`); revisit together if/when this project moves to a real multi-process deployment.

## Consequences

- Orphaned containers are now bounded in lifetime (at most ~2 poll intervals past whenever they actually became orphaned) instead of accumulating indefinitely until someone notices and does a manual `docker ps` sweep.
- Every automatic termination is audited (`ORPHAN_SESSION_RECONCILED`) and visible on the admin dashboard — no silent cleanup.
- A `user`-only split-deployment process (`OPENRBI_LISTENER_MODE=user`, `docs/adr/0011`) does not run this reconciler, matching `node_poller`'s existing behavior — a pure user-facing process was never the one managing node-wide telemetry or cleanup. A deployment running only `user`-mode processes with no `admin`/`both` process at all would have no reconciliation running; this mirrors an existing, already-accepted gap for `node_poller` telemetry and is not new to this change.
- The Session Agent's `SandboxProvider` protocol gained one more required method (`list_active_session_ids`) — any future alternative provider (gVisor, Kata) must implement it.
