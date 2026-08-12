# Admin Guide

> Status (Productization v0.1.1): a real Admin Portal now exists (`frontend/admin/`), built against the Admin listener's API and verified end-to-end in a real browser against the live stack — login+mandatory MFA, dashboard, user creation, session isolate/kill with confirmation dialogs, quarantine review, and the system health/nodes view. Sections below describe the portal UI; the underlying API each screen calls is still documented for direct integration. All endpoints require ADMIN or SECURITY_REVIEWER unless stated otherwise; a plain USER gets `403` (in Compact/`both` mode) or the route doesn't exist at all (in a real `user`-mode listener — see [ADR 0011](adr/0011-user-admin-listener-separation.md)).

## Logging in

Open the Admin Portal (Compact: `/admin/` on the same origin as the reverse proxy; Segmented: your organization's dedicated Admin Portal origin). MFA is mandatory for ADMIN and SECURITY_REVIEWER — the portal walks a not-yet-enrolled account through QR-code enrollment before issuing a session, exactly like the User Portal's flow (they share the same component).

## Dashboard

Shows active/isolated session counts, open incidents, quarantine items awaiting review, and overall system health as KPI cards — all aggregated client-side from the same list/health endpoints described below (there is no dedicated dashboard-stats endpoint yet; see [architecture.md](architecture.md) for this documented gap). Never a fabricated chart — if there's no time-series API, there's no chart for it.

**Needs attention** lists real, current problems only: open high/critical incidents, isolated sessions, quarantined files awaiting review, and any degraded health component. When there are none, it says so plainly instead of showing an empty table or inventing something to display. **Recent activity** is a feed of the latest real security events, not a separate log.

## Help and Notifications

Every page in both portals has a **Help** menu (top bar) linking to the real Markdown docs in this `docs/` folder, served by nginx directly from the deployed image — not a hardcoded external URL that would 404 on an offline or air-gapped deployment. The **Notifications** button is honest about the platform not having a real notification/alerting feed yet: it opens to an explicit "No notifications yet" state rather than being filled with placeholder entries.

## Users and groups

**Users**: create, view, enable/disable, reset password, reset MFA. Creating a user is a real form against `POST /admin/users` (username, initial password, role, groups) — the backend, not the form, is authoritative on password rules. A user's detail page shows their groups, MFA status, and their sessions, with the same Disconnect/Isolate/Restore/Kill actions available inline. Promoting a user to ADMIN/SECURITY_REVIEWER doesn't retroactively force MFA — it's re-checked from the user's *current* role at their very next login.

**Groups**: create/delete from the Groups page. Group membership is set when creating a user or from their detail page.

Every disable, MFA reset, or role change is a security-critical action — the portal shows a specific confirmation ("Reset MFA for X? ... they will be required to re-enroll on their next login"), never a bare "Are you sure?".

<details><summary>Underlying API</summary>

`POST/GET /admin/users`, disable/enable, admin password reset, role reassignment, group membership (`app/api/admin.py`), plus `POST/GET /admin/groups` and `DELETE /admin/groups/{id}`, and `POST /mfa/admin/users/{id}/reset` (`app/api/admin_mfa.py`).
</details>

## Sessions

The Sessions page lists every session on the system with client-side status/username filtering (the backend has no server-side filter or pagination on this endpoint yet — a documented gap, not something the UI silently pretends to have). Session detail shows full lifecycle info, resource limits, and recent security events, with Disconnect/Isolate/Restore/Kill buttons shown only when the session's current status actually allows that action. **Isolate** and **Kill** show specific, honest confirmation dialogs (e.g. *"Kill session S-1234? This immediately terminates the user's browser sandbox. Unsaved browser state will be lost."*) — verified live: isolating a real session actually leaves its sandbox container with zero attached Docker networks, and killing one actually removes the container.

<details><summary>Underlying API</summary>

`GET /admin/sessions`, `GET /admin/sessions/{id}`, `GET /admin/users/{id}/sessions`, `POST /admin/sessions/{id}/{disconnect,isolate,restore,kill}`. Disconnect and Isolate are available to both ADMIN and SECURITY_REVIEWER; Kill is ADMIN-only (the project brief doesn't specify which role Kill needs — read as the more restrictive option when ambiguous, see [session-lifecycle.md](session-lifecycle.md)). Isolating a session always opens an Incident in addition to the `SESSION_ISOLATED` security event.
</details>

## Nodes (System page)

Lists every `BrowserNode` (single node in MVP 1, but modeled as a real list) with a **Drain**/**Undrain** action. Draining stops new sessions from being scheduled onto that node without disturbing sessions already running on it.

## Policies

The Policies page and its per-policy detail view give the existing policy engine a structured editor — a rule builder (rule type, match pattern, action, priority), never a raw JSON textbox as the primary UX. Draft → publish → rollback all work through real buttons. **Only MIME/SOURCE file rules are actually enforced** — the editor only offers those two rule types for exactly that reason; see [policies.md#what-a-policys-policy_type-actually-does](policies.md#what-a-policys-policy_type-actually-does) before creating a `NETWORK`/`CLIPBOARD`/`BROWSER`/`SESSION`-labeled policy expecting it to do something at runtime — the portal still lets you create one (matching the backend, which also allows it), with a hint explaining why it won't do anything.

<details><summary>Underlying API</summary>

Full draft → publish → rollback workflow under `/admin/policies/*` — see [policies.md](policies.md) for the conflict model and versioning rules. A published version is immutable; editing one always means creating a new draft (`PUT .../versions/{id}` while still `DRAFT`, or `POST .../versions` for a brand new one).
</details>

## Quarantine review

The Quarantine page filters by status (defaulting to `QUARANTINED`, the actionable state) and each file's detail page shows exactly the metadata a reviewer needs — hash, source, detected MIME, scanner result — and nothing else. **There is no file preview** — verified deliberately absent, matching the project's own "no safe preview mechanism in MVP 1" scope. Release and Reject both ask for an optional comment and a specific confirmation before acting; re-deciding an already-decided file is rejected by the backend (`409`), not silently accepted.

<details><summary>Underlying API</summary>

`POST /admin/quarantine/{id}/{release,reject}` — only ever actionable on a file still `QUARANTINED`. See [quarantine.md](quarantine.md) for the full pipeline a file goes through before it ever reaches this state.
</details>

## System (Health)

Real `GET /admin/health` output, component by component — never a hardcoded green check. Verified live by actually stopping ClamAV and the Session Agent during development and confirming the page correctly showed `UNAVAILABLE`/`DEGRADED` for exactly the affected components, not a generic failure.

<details><summary>Underlying API</summary>

`GET /admin/health` aggregates independent checks of every dependency: API, PostgreSQL, Redis, Session Agent, sandbox runtime, browser-image availability, ClamAV, and quarantine-storage writability. Overall `status` is `HEALTHY` only if every component is; `UNAVAILABLE` if the API or PostgreSQL itself is down; otherwise `DEGRADED`. See [architecture.md#health-monitoring-phase-19](architecture.md#health-monitoring-phase-19) for why this endpoint — unlike the plain unauthenticated `GET /health` liveness probe — is itself unreachable during a full PostgreSQL outage.
</details>

## Audit

Shows event type, actor/user, session, and timestamp by default; a **Show raw event** toggle per row reveals the full structured metadata for technical review — never a wall of raw JSON as the default view. Filterable by event type, paginated.

<details><summary>Underlying API</summary>

`GET /admin/security-events` (filterable by `event_type`/`user_id`/`session_id`, paginated via `limit`/`offset`) — read-only, append-only; see [api.md](api.md#audit--security-events-phase-18).
</details>

## Incidents (Phase 17)

`GET /admin/incidents` (filterable by `status_filter`/`severity_filter`), `GET /admin/incidents/{id}`, and `PUT /admin/incidents/{id}` (set `status`, `assigned_to`, `resolution`) are available to ADMIN and SECURITY_REVIEWER accounts (matching §6's explicit "Incidents bearbeiten" reviewer right).

Incidents are created automatically for:
- Malware detected in a download or upload (Phase 14/16) — `CRITICAL`.
- An admin/reviewer isolating a session (Phase 11) — `MEDIUM`.
- Repeated blocked file transfers by the same user within a 15-minute window (3+ `DOWNLOAD_BLOCKED`/`UPLOAD_BLOCKED` events) — `HIGH`. Deliberately not one-incident-per-blocked-transfer (§21: "nicht jeder einzelne geblockte Download darf automatisch ein Incident werden") — a user already under an open incident for this doesn't get a second one for further blocked attempts, avoiding alert fatigue.

Not yet automated (tracked gaps, not silently skipped): repeated `NETWORK_ACCESS_BLOCKED` events, since Phase 9's network isolation currently only logs blocked connections at the kernel level — no application-layer `SecurityEvent` exists yet to aggregate on (see docs/security-model.md's interim gaps).
