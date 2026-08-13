# Admin Guide

> Status (Productization v0.1.1): a real Admin Portal now exists (`frontend/admin/`), built against the Admin listener's API and verified end-to-end in a real browser against the live stack — login+mandatory MFA, dashboard, user creation, session isolate/kill with confirmation dialogs, quarantine review, and the system health/nodes view. Sections below describe the portal UI; the underlying API each screen calls is still documented for direct integration. All endpoints require ADMIN or SECURITY_REVIEWER unless stated otherwise; a plain USER gets `403` (in Compact/`both` mode) or the route doesn't exist at all (in a real `user`-mode listener — see [ADR 0011](adr/0011-user-admin-listener-separation.md)).

## First-run setup (Roadmap B1.9)

A brand new installation has no user accounts at all. Opening the Admin Portal for the first time shows **Initial System Setup** instead of the login form — no manual database access is ever required to create the first administrator. See [docs/deployment.md#first-run-setup-roadmap-b19](deployment.md#first-run-setup-roadmap-b19) for the full walkthrough (retrieving the console-logged setup token, creating the account, completing mandatory MFA enrollment). Once that flow completes, this screen is gone permanently for this installation — a new browser, a new admin account, or even every existing account being deleted does **not** bring it back (see [ADR 0017](adr/0017-first-run-bootstrap.md)). **Keep at least one local `ADMIN` account with a real password at all times** — it is the only account guaranteed to work through any LDAP outage or misconfiguration, and there is currently no separate account-recovery process if every local administrator is lost.

## Logging in

Open the Admin Portal (Compact: `/admin/` on the same origin as the reverse proxy; Segmented: your organization's dedicated Admin Portal origin). MFA is mandatory for ADMIN and SECURITY_REVIEWER — the portal walks a not-yet-enrolled account through QR-code enrollment before issuing a session, exactly like the User Portal's flow (they share the same component). This applies identically to a local or an LDAP-authenticated login (see below) — there is no way to reach an ADMIN/SECURITY_REVIEWER session without MFA regardless of which one authenticated the request.

## LDAP/LDAPS authentication (Roadmap Phase B / B1)

An equal, parallel login option alongside local accounts — never a replacement. Local login always stays available, including for the entire duration of an LDAP outage; there is no way to disable it. See [ADR 0015](adr/0015-auth-provider-abstraction.md) for the authentication design and [ADR 0016](adr/0016-ldap-admin-configuration.md) for the admin-portal configuration layer described below (Roadmap B1.8).

### Configuring LDAP via the Admin Portal (recommended)

Go to **Settings → Authentication → LDAP** (`ADMIN` role required — `SECURITY_REVIEWER` cannot read or change this). The page is available whether or not LDAP has ever been configured before; a fresh install shows an empty form.

Fill in the connection fields (server URI, StartTLS, bind DN, bind password, base DN, user search filter, group attribute) and use **Test connection** before saving — this runs the exact same connection/bind/search code a real login uses, reports each step (TLS/connection, service bind, search base, and, if a test username is given, user search and group resolution) as OK or FAILED with an admin-readable reason, and never touches the saved configuration either way.

Click **Save configuration**. If the `Enabled` checkbox is on, the save itself re-runs that same connection test server-side first — a broken configuration is rejected (the form stays as you left it, with a toast explaining the test failed) and the **previously saved, working configuration is left completely untouched**. Saving with `Enabled` off never requires a passing test, so you can save a work-in-progress configuration without risking the currently-active one.

**Secret handling**: the bind password is never returned by any API response and never appears in the audit log — the field is always shown empty, with a "Bind password: configured — leave empty to keep the existing password" hint once one has been saved. Leaving it empty on a later save keeps the existing password; typing a new value replaces it. It is encrypted at rest using the same key that protects TOTP secrets (`OPENRBI_TOTP_SECRET_ENCRYPTION_KEY`).

**Group → role mapping** is an editable table on the same page — LDAP group DN → OpenRBI role. It replaces `OPENRBI_LDAP_GROUP_ROLE_MAPPING` for any installation that has saved a configuration through the portal (see priority below); the matching semantics are unchanged (exact-string DN match, `ADMIN` > `SECURITY_REVIEWER` > `USER` precedence, no match → `USER`).

Once any configuration has been saved through the Admin Portal, it is fully authoritative — the `OPENRBI_LDAP_*` environment variables are no longer consulted at all, not even for fields left at their default. LDAP can be enabled, reconfigured, or disabled entirely from the portal, with no backend restart required.

### Configuring LDAP via environment variables (bootstrap / fresh install only)

Set in `.env` and restart `backend` (see `.env.example` for the full list with descriptions) — this is only consulted when **no configuration has ever been saved through the Admin Portal**:

```
OPENRBI_LDAP_ENABLED=true
OPENRBI_LDAP_SERVER_URI=ldaps://your-ad-server:636      # or ldap://... with StartTLS left on
OPENRBI_LDAP_BIND_DN=...          # a dedicated search/service account, not an admin's own credentials
OPENRBI_LDAP_BIND_PASSWORD=...
OPENRBI_LDAP_BASE_DN=DC=example,DC=org
OPENRBI_LDAP_GROUP_ROLE_MAPPING={"CN=OpenRBI-Admins,OU=Groups,DC=example,DC=org": "ADMIN"}
```

A plain `ldap://` URI with StartTLS turned off is refused (both here and in the Admin Portal) — there is no supported way to configure an unencrypted bind. `OPENRBI_LDAP_GROUP_ROLE_MAPPING` is a JSON object with the same shape and matching rules as the portal's mapping table.

**Required LDAP permissions for the service account** (the bind DN) — read access to the base DN subtree, sufficient to search for a user by the configured filter and read the configured group attribute. No write access of any kind is needed; OpenRBI never modifies anything in the directory.

**How a login is resolved** — on `/auth/login`, local is always tried first. LDAP is only attempted if the local check fails *and* LDAP is currently enabled (Admin Portal configuration if one exists, otherwise the environment variables above) — so an account with a real local password is checked against that password first, with no network round-trip, before LDAP is ever consulted.

**First login for a new AD user** — if no local account exists for that exact username, one is created automatically ("just-in-time provisioning") with the role resolved from the bind's group membership, and no local password stored (LDAP credentials are never cached). Matching is by **exact username string only** — no name/birthdate/other-attribute matching is attempted, deliberately: a fuzzy match risks linking the wrong local account to a different real person, which is a direct account-takeover path. If your local and LDAP usernames genuinely differ for the same person, they are treated as two separate accounts.

**Role authority when a username exists both locally (with a real password) and in LDAP** — the local account's role is authoritative and is **never** overwritten by an LDAP group login, even if that LDAP login succeeds. This specifically protects a deliberately-provisioned local account (e.g. an emergency ADMIN access path that should keep working even if someone's AD group memberships change or lapse) from being silently downgraded by an incidental LDAP login. Role is only ever re-derived from current LDAP groups for an account that was itself LDAP-provisioned (no local password) — for that account, the mapped role is re-checked on every login, the same "recompute from current source of truth" principle already applied to MFA-mandatory-role enforcement.

**If the LDAP server is unreachable or a TLS handshake fails**, login for LDAP-only accounts is denied — the same generic "invalid credentials" response as a wrong password, never a silent fallback to any outcome that grants access. Local accounts are completely unaffected and keep working throughout. There is currently no dedicated "LDAP is down" indicator in the Admin Portal beyond this — an admin noticing a wave of LDAP-account login failures during a real outage should check LDAP server reachability directly.

**Known limitation**: group DN matching (env or Admin Portal mapping table) is exact-string, case-sensitive — it does not normalize DN casing or attribute ordering. Configure the mapping using the DN exactly as your directory returns it (verify with a real `ldapsearch` against a test account, or the portal's "Test connection" with a test username, if login resolves to `USER` unexpectedly).

**Break-glass / local admin access**: keep at least one local `ADMIN` account with a real password at all times. Because local login is always tried first and a local password is always authoritative for its own account (see role-authority rule above), this account keeps working through any LDAP outage or misconfiguration — including one introduced while editing the LDAP settings themselves — and can always be used to fix a broken LDAP configuration from the Admin Portal. There is no other account-recovery mechanism today; losing access to every local `ADMIN` account is a known Productization gap, tracked as a follow-up (a dedicated recovery process, separate from the public first-run setup, is out of scope for B1.8/B1.9 and not yet implemented).

**Audit**: every LDAP configuration change, enable, disable, and connection test is recorded as a security event (`LDAP_CONFIG_CHANGED`, `LDAP_ENABLED`, `LDAP_DISABLED`, `LDAP_CONNECTION_TESTED`, viewable under Audit) with the actor and safe metadata (server URI, StartTLS, base DN, whether the password changed) — never the bind password, TOTP secrets, or any other credential.

## Dashboard

Shows active/isolated session counts, open incidents, quarantine items awaiting review, overall system health, and the most recent security events — all aggregated client-side from the same list/health endpoints described below (there is no dedicated dashboard-stats endpoint yet; see [architecture.md](architecture.md) for this documented gap). Never a fabricated chart — if there's no time-series API, there's no chart for it.

## Users and groups

**Users**: create, view, enable/disable, reset password, reset MFA, lock/unlock the login, terminate all sessions. Creating a user is a real form against `POST /admin/users` (username, initial password, role, groups) — the backend, not the form, is authoritative on password rules. A user's detail page shows their groups, MFA status, current login-lockout state, and their sessions, with the same Disconnect/Isolate/Restore/Kill actions available inline, plus a **Terminate all sessions** button (Roadmap B1.10.4) shown only when the user has at least one live session. Promoting a user to ADMIN/SECURITY_REVIEWER doesn't retroactively force MFA — it's re-checked from the user's *current* role at their very next login.

**Login lockout / Account Lock (Roadmap B1.10.5)**: the same brute-force lockout the system already applies automatically after repeated failed logins is now visible and admin-controllable — the User Detail page shows whether the account is currently locked (and, while locked, roughly how long until it clears on its own), with **Lock account**/**Unlock account** buttons. Lock is not the same thing as Disable: Disable is a separate, persistent "account deactivated" state; Lock only blocks new logins for the same window an automatic lockout would, and also immediately revokes any session the account currently has. An MFA reset does the same session-revocation, since MFA is otherwise only re-checked at login time — a reset previously left an already-issued session valid until it expired on its own.

**Groups**: create/delete from the Groups page. Group membership is set when creating a user or from their detail page.

Every disable, MFA reset, lock, or role change is a security-critical action — the portal shows a specific confirmation ("Reset MFA for X? ... they will be required to re-enroll on their next login"), never a bare "Are you sure?".

<details><summary>Underlying API</summary>

`POST/GET /admin/users`, disable/enable, admin password reset, role reassignment, group membership, `GET /admin/users/{id}/lockout`, `POST /admin/users/{id}/{lock,unlock}`, `POST /admin/users/{id}/sessions/revoke` (`app/api/admin.py`), plus `POST/GET /admin/groups` and `DELETE /admin/groups/{id}`, and `POST /mfa/admin/users/{id}/reset` (`app/api/admin_mfa.py`).
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
