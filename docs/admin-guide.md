# Admin Guide

> Status: there is no admin portal UI (see [architecture.md#status](architecture.md#status)) — every section below describes the real, usable backend API instead. All endpoints require ADMIN or SECURITY_REVIEWER unless stated otherwise; a plain USER gets `403` on all of them.

## User and group management

`POST/GET /admin/users`, disable/enable, admin password reset, role reassignment, group membership (`app/api/admin.py`), plus `POST/GET /admin/groups` and `DELETE /admin/groups/{id}`. Promoting a user to ADMIN/SECURITY_REVIEWER doesn't retroactively force MFA — it's re-checked from the user's *current* role at their very next login, so the promoted account is walked through mandatory enrollment the first time it logs in under the new role, not before.

## Session control

`GET /admin/sessions`, `GET /admin/users/{id}/sessions` for oversight, and `POST /admin/sessions/{id}/{disconnect,isolate,restore,kill}`. Disconnect and Isolate are available to both ADMIN and SECURITY_REVIEWER; Kill is ADMIN-only (the project brief doesn't specify which role Kill needs — read as the more restrictive option when ambiguous, see [session-lifecycle.md](session-lifecycle.md)). Isolating a session always opens an Incident in addition to the `SESSION_ISOLATED` security event.

## Nodes

`GET /admin/nodes` lists every `BrowserNode` (single node in MVP 1, but modeled as a real list — see [architecture.md#multi-node-readiness](architecture.md#multi-node-readiness)). `POST /admin/nodes/{id}/drain` stops new sessions from being scheduled onto that node without disturbing sessions already running on it; `POST /admin/nodes/{id}/undrain` reverses it. Both are ADMIN-only and generate a `NODE_DRAINED` security event.

## Policies

Full draft → publish → rollback workflow under `/admin/policies/*` — see [policies.md](policies.md) for the conflict model and versioning rules. A published version is immutable; editing one always means creating a new draft. **Only MIME/SOURCE file rules are actually enforced** — see [policies.md#what-a-policys-policy_type-actually-does](policies.md#what-a-policys-policy_type-actually-does) before creating a `NETWORK`/`CLIPBOARD`/`BROWSER`/`SESSION`-labeled policy expecting it to do something at runtime.

## Quarantine review

`POST /admin/quarantine/{id}/{release,reject}` — only ever actionable on a file still `QUARANTINED`; re-deciding an already-decided file is `409`, not silently accepted. See [quarantine.md](quarantine.md) for the full pipeline a file goes through before it ever reaches this state, and for why the reviewer only ever sees captured metadata (hash, source, MIME, scan result), never the file's actual content.

## Health monitoring

`GET /admin/health` aggregates independent checks of every dependency: API, PostgreSQL, Redis, Session Agent, sandbox runtime, browser-image availability, ClamAV, and quarantine-storage writability. Overall `status` is `HEALTHY` only if every component is; `UNAVAILABLE` if the API or PostgreSQL itself is down; otherwise `DEGRADED`. See [architecture.md#health-monitoring-phase-19](architecture.md#health-monitoring-phase-19) for why this endpoint — unlike the plain unauthenticated `GET /health` liveness probe — is itself unreachable during a full PostgreSQL outage, and [troubleshooting.md](troubleshooting.md) for what to do with a `DEGRADED`/`UNAVAILABLE` component.

## Audit / security events

`GET /admin/security-events` (filterable by `event_type`/`user_id`/`session_id`, paginated) — read-only, append-only; see [api.md](api.md#audit--security-events-phase-18).

## Incidents (Phase 17)

`GET /admin/incidents` (filterable by `status_filter`/`severity_filter`), `GET /admin/incidents/{id}`, and `PUT /admin/incidents/{id}` (set `status`, `assigned_to`, `resolution`) are available to ADMIN and SECURITY_REVIEWER accounts (matching §6's explicit "Incidents bearbeiten" reviewer right).

Incidents are created automatically for:
- Malware detected in a download or upload (Phase 14/16) — `CRITICAL`.
- An admin/reviewer isolating a session (Phase 11) — `MEDIUM`.
- Repeated blocked file transfers by the same user within a 15-minute window (3+ `DOWNLOAD_BLOCKED`/`UPLOAD_BLOCKED` events) — `HIGH`. Deliberately not one-incident-per-blocked-transfer (§21: "nicht jeder einzelne geblockte Download darf automatisch ein Incident werden") — a user already under an open incident for this doesn't get a second one for further blocked attempts, avoiding alert fatigue.

Not yet automated (tracked gaps, not silently skipped): repeated `NETWORK_ACCESS_BLOCKED` events, since Phase 9's network isolation currently only logs blocked connections at the kernel level — no application-layer `SecurityEvent` exists yet to aggregate on (see docs/security-model.md's interim gaps).
