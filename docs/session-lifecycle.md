# Session Lifecycle

## Implementation status

The full state machine is real and backend-orchestrated: `POST /sessions` (Phase 10, `app/services/sessions.py`) drives create→start→wait-for-display-ready→`ACTIVE`; the display WebSocket (`app/api/display.py`) drives `ACTIVE ⇄ DISCONNECTED` from actual client connect/disconnect; and the admin actions (Phase 11, `app/api/admin_sessions.py`) drive `ISOLATING → ISOLATED`, `ISOLATED → ACTIVE` (restore), and `TERMINATING → TERMINATED` (kill), each backed by the Session Agent's real Docker-level primitives (Phase 6) — isolate actually disconnects the sandbox's network, kill actually removes the container.

**Role assumption** (documented per the project's own "pick the more restrictive reading when ambiguous" principle): the project brief lists Disconnect/Isolate/Kill together under "User Detail Actions" without stating which role each requires, while §6 explicitly grants only Isolate to `SECURITY_REVIEWER`. Disconnect and Isolate are available to both `ADMIN` and `SECURITY_REVIEWER`; Kill is `ADMIN`-only. An admin-triggered Isolate also always opens an Incident (`MEDIUM` severity), matching the project brief's Definition-of-Done walkthrough (§37, step 25) — not just a security event.

Admin-forced Disconnect closes the user's live display WebSocket immediately via an in-process connection registry (`app/api/display.py`'s `_active_connections`) — single-backend-process in v1.0; a real multi-instance deployment would need this shared (e.g. Redis pub/sub) instead.

## States

| State | Meaning |
|---|---|
| `QUEUED` | Session requested, waiting on node/capacity selection |
| `STARTING` | Sandbox + display are being created/started |
| `ACTIVE` | Sandbox running and its display ready, session usable — set once the display is ready (before any viewer connects), on reconnect, and after a restore |
| `DISCONNECTED` | Remote-display connection dropped; sandbox still running |
| `ISOLATING` | Isolation in progress (network/clipboard/file-transfer being locked down) |
| `ISOLATED` | Network egress, clipboard (both directions), uploads, new downloads, and new file shares are all denied; sandbox still exists |
| `TERMINATING` | Sandbox teardown in progress |
| `TERMINATED` | Sandbox fully destroyed; terminal state |
| `FAILED` | Unrecoverable error during any transition; terminal state |

## Transitions

```
QUEUED → STARTING → ACTIVE ⇄ DISCONNECTED
                       │           │
                       ▼           ▼
                   ISOLATING → ISOLATED ──restore──▶ ACTIVE

any state except TERMINATED ──kill / end session──▶ TERMINATING → TERMINATED

any state → FAILED (on unrecoverable error)
```

- `ACTIVE → DISCONNECTED`: the remote-display connection drops (client closed tab, network blip). The sandbox is not touched. The session owner can reconnect by opening the Secure Browser again (`DISCONNECTED → ACTIVE`); admins have no viewer and cannot reconnect to someone else's session. If nobody does within `OPENRBI_SESSION_DISCONNECTED_TIMEOUT_SECONDS` (default 3600, `0` disables it), `app/core/session_reaper.py` moves it to `TERMINATING → TERMINATED` automatically and records `SESSION_TIMED_OUT`. The disconnect time is `last_activity_at`, stamped when the display connection drops. An `ACTIVE` session that nobody has viewed since it started or was restored (for example, the tab was closed while it said "Connecting display…") times out the same way, measured from the start or restore and audited with reason `no_viewer_timeout`; the backend records an open viewer connection in `viewer_connected_at`. There is no idle timeout while a viewer is connected, and `ISOLATED` sessions are never timed out.
- `ACTIVE/DISCONNECTED → ISOLATING → ISOLATED`: admin- or Security-Reviewer-triggered only — there is no automatic isolation in v1.0. Always generates a `SESSION_ISOLATED` Security Event and opens a `MEDIUM` Incident. The sandbox is kept for investigation: its owner can no longer end it (see below), and it no longer counts toward `OPENRBI_MAX_SESSIONS_PER_USER`, so the owner can start a new session at once. The User Portal keeps a notice for it until an administrator ends it.
- `ISOLATED → ACTIVE`: explicit "restore" action by an authorized admin/reviewer — logged as its own Security Event, distinct from the original isolation.
- `any state except TERMINATED → TERMINATING → TERMINATED`: Kill (ADMIN) or **End session** (the owning user, `POST /sessions/{id}/terminate`). The owner can't end an `ISOLATING` or `ISOLATED` session: the terminate call answers `409` and leaves it untouched, so only an administrator's Kill (or Restore) ends the isolation. Idempotent — killing an already-terminated or already-terminating session succeeds (or no-ops) rather than erroring. The backend accepts this for `QUEUED`, `STARTING` and `FAILED` sessions too; for a `FAILED` session the Admin Portal offers it as **Clean up**, which removes what's left of the sandbox at once instead of waiting for orphan reconciliation and marks the session `TERMINATED` (the failure stays in the audit log).
- Any state can move to `FAILED` if the underlying `SandboxProvider`/`DisplayProvider` call fails unrecoverably; `FAILED` sessions still require cleanup (best-effort termination) and are surfaced to admins, not silently dropped.

## Admin actions

| Action | Effect on sandbox | Effect on network/clipboard/files | Idempotent |
|---|---|---|---|
| Disconnect | Unaffected | Unaffected | Yes |
| Isolate | Unaffected (persists for investigation) | Network egress DENY ALL; clipboard DENY both directions; uploads DENY; new downloads DENY; new file shares DENY | Yes |
| Kill | Fully destroyed | N/A (sandbox gone) | Yes |

Every Disconnect, Isolate, Restore, and Kill action is attributed to the acting admin/reviewer and recorded as a Security Event; Isolate additionally triggers Incident creation/aggregation logic (see the project's incident rules — not every single blocked action becomes its own incident, to avoid alert fatigue).

## Error states

A session whose sandbox container disappears while it's `ACTIVE`, `DISCONNECTED`, `ISOLATING`, or `ISOLATED` is marked `FAILED` by orphan reconciliation (`app/core/orphan_reconciler.py`, `SESSION_LOST_RECONCILED`) and surfaced to admins, rather than left in an ambiguous state indefinitely. A session stuck in `STARTING` or `TERMINATING` for longer than `OPENRBI_SESSION_STUCK_TRANSITION_TIMEOUT_SECONDS` (default 600, `0` disables it, measured from the row's `updated_at`) is torn down again through the normal, idempotent terminate path by `app/core/session_reaper.py` and audited as `SESSION_TIMED_OUT` with reason `stuck_starting` or `stuck_terminating`. A normal create or terminate finishes in seconds; a row only stays in either state when the backend stopped mid-transition. If that teardown fails too, the session is `FAILED` and orphan reconciliation removes its container once the Session Agent is reachable again.
