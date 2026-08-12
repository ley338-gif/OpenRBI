# Session Lifecycle

## Implementation status

`QUEUED → STARTING → ACTIVE ⇄ DISCONNECTED → TERMINATING → TERMINATED/FAILED` is real and backend-orchestrated (`app/services/sessions.py`, Phase 10): `POST /sessions` drives the full create→start→wait-for-display-ready→ACTIVE sequence against the Session Agent, and the display WebSocket (`app/api/display.py`) drives the `ACTIVE ⇄ DISCONNECTED` transitions from actual client connect/disconnect. `ISOLATING`/`ISOLATED` exist in the model and the Session Agent already supports the underlying `isolate`/`restore` primitives (Phase 6), but the admin-facing trigger for them is Phase 11.

## States

| State | Meaning |
|---|---|
| `QUEUED` | Session requested, waiting on node/capacity selection |
| `STARTING` | Sandbox + display are being created/started |
| `ACTIVE` | Sandbox running, display connected, session usable |
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
                    ISOLATING → ISOLATED
                        │           │
                        └─────┬─────┘
                              ▼
                        TERMINATING → TERMINATED

any state → FAILED (on unrecoverable error)
```

- `ACTIVE → DISCONNECTED`: the remote-display connection drops (client closed tab, network blip). The sandbox is not touched. A user or admin can reconnect (`DISCONNECTED → ACTIVE`) or the session can time out and move to `TERMINATING`.
- `ACTIVE/DISCONNECTED → ISOLATING → ISOLATED`: admin- or Security-Reviewer-triggered, or automatic on policy violation. Always generates a Security Event; automatic isolation also opens/updates an Incident.
- `ISOLATED → ACTIVE`: explicit "restore" action by an authorized admin/reviewer — logged as its own Security Event, distinct from the original isolation.
- `ISOLATED/ACTIVE/DISCONNECTED → TERMINATING → TERMINATED`: Kill. Must be idempotent — killing an already-terminated or already-terminating session succeeds (or no-ops) rather than erroring.
- Any state can move to `FAILED` if the underlying `SandboxProvider`/`DisplayProvider` call fails unrecoverably; `FAILED` sessions still require cleanup (best-effort termination) and are surfaced to admins, not silently dropped.

## Admin actions

| Action | Effect on sandbox | Effect on network/clipboard/files | Idempotent |
|---|---|---|---|
| Disconnect | Unaffected | Unaffected | Yes |
| Isolate | Unaffected (persists for investigation) | Network egress DENY ALL; clipboard DENY both directions; uploads DENY; new downloads DENY; new file shares DENY | Yes |
| Kill | Fully destroyed | N/A (sandbox gone) | Yes |

Every Disconnect, Isolate, Restore, and Kill action is attributed to the acting admin/reviewer and recorded as a Security Event; Isolate additionally triggers Incident creation/aggregation logic (see the project's incident rules — not every single blocked action becomes its own incident, to avoid alert fatigue).

## Error states

A session stuck in `STARTING`, `ISOLATING`, or `TERMINATING` past a configurable timeout is treated as `FAILED` and surfaced to admins with the last known provider status, rather than left in an ambiguous state indefinitely.
