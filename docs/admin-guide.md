# Admin Guide

> Status: placeholder for most sections — the admin portal UI is not yet implemented (see [development.md](development.md) for build phases). Backend APIs for user/group management (Phase 5), session control (Phase 11), policies (Phase 12), quarantine review (Phase 15), and incidents (Phase 17, below) already exist and are usable directly.

## Incidents (Phase 17)

`GET /admin/incidents` (filterable by `status_filter`/`severity_filter`), `GET /admin/incidents/{id}`, and `PUT /admin/incidents/{id}` (set `status`, `assigned_to`, `resolution`) are available to ADMIN and SECURITY_REVIEWER accounts (matching §6's explicit "Incidents bearbeiten" reviewer right).

Incidents are created automatically for:
- Malware detected in a download or upload (Phase 14/16) — `CRITICAL`.
- An admin/reviewer isolating a session (Phase 11) — `MEDIUM`.
- Repeated blocked file transfers by the same user within a 15-minute window (3+ `DOWNLOAD_BLOCKED`/`UPLOAD_BLOCKED` events) — `HIGH`. Deliberately not one-incident-per-blocked-transfer (§21: "nicht jeder einzelne geblockte Download darf automatisch ein Incident werden") — a user already under an open incident for this doesn't get a second one for further blocked attempts, avoiding alert fatigue.

Not yet automated (tracked gaps, not silently skipped): repeated `NETWORK_ACCESS_BLOCKED` events, since Phase 9's network isolation currently only logs blocked connections at the kernel level — no application-layer `SecurityEvent` exists yet to aggregate on (see docs/security-model.md's interim gaps).
