# OpenRBI v1.0 Release Acceptance

This is the binding v1 release acceptance record. A commit is accepted only
when its own GitHub `Release gates` check is green; results from an older commit
are not transferable. The suite uses real PostgreSQL, Valkey, ClamAV, LDAP,
Docker runtime and browser containers. Mocks do not count as evidence for the
scenarios below.

Recorded: 2026-08-15  
Candidate baseline: `00a2f14922dfe9067b9aa7b9d24178032588245f`  
Overall result: **PASS — 35/35 scenarios**  
Authoritative automation: `.github/workflows/ci.yml` → `Release gates`

The baseline's [main CI run](https://github.com/ley338-gif/OpenRBI/actions/runs/31863930779)
completed successfully, including the aggregate `Release gates` result. The
commit that adds or changes this record must pass its own gates as well before
merge and before it can become an RC target.

Evidence abbreviations:

- **FI** — [`fault-injection-acceptance.md`](fault-injection-acceptance.md)
- **FR** — [`fresh-install-acceptance.md`](fresh-install-acceptance.md)
- **SR** — [`security-review.md`](security-review.md)
- **BR** — [`backup-restore-acceptance.md`](backup-restore-acceptance.md)
- **UP** — [`upgrade-acceptance.md`](upgrade-acceptance.md)
- **CI** — required GitHub workflow jobs defined in `.github/workflows/ci.yml`

## Installation and authentication

### 1. Clean Installation

- **Preconditions:** Empty dedicated Compose project, no acceptance `.env`, no volumes.
- **Steps:** Generate secrets; build/start Compact stack; migrate empty PostgreSQL; build browser image; apply isolation.
- **Expected Result:** Installation completes without manual DB edits and every required service is reachable.
- **Actual Result:** Fresh generated environment completed all 16 executable install steps and cleaned itself up.
- **Status:** **PASS**
- **Evidence:** FR steps 1–8 and 16; CI `Fresh install acceptance`.

### 2. Initial Admin Setup

- **Preconditions:** Fresh uninitialized database and console access to the one-time setup token.
- **Steps:** Query setup status; submit token and ADMIN credentials through the setup API.
- **Expected Result:** Exactly one initial ADMIN is created without direct SQL; setup cannot be repeated.
- **Actual Result:** Console-only token created the initial ADMIN and setup closed permanently after completion.
- **Status:** **PASS**
- **Evidence:** FR step 9; `backend/tests/integration/test_setup.py`; SR Bootstrap row.

### 3. Admin MFA Enrollment

- **Preconditions:** Initial ADMIN exists and has no enrolled factor.
- **Steps:** Enroll TOTP; confirm a live code; capture recovery codes.
- **Expected Result:** MFA becomes mandatory, secret is encrypted, recovery codes are returned once.
- **Actual Result:** Live TOTP confirmation succeeded and setup issued one-time recovery codes.
- **Status:** **PASS**
- **Evidence:** FR step 10; `backend/tests/integration/test_auth_and_mfa.py`; SR MFA row.

### 4. Admin Login

- **Preconditions:** Initialized ADMIN with enrolled MFA; setup session discarded.
- **Steps:** Password login; complete MFA with a fresh TOTP; call `/auth/me`.
- **Expected Result:** Server-side session identifies role `ADMIN`; password alone is insufficient.
- **Actual Result:** Fresh two-stage login returned an authenticated ADMIN session.
- **Status:** **PASS**
- **Evidence:** FR step 11; CI `Fresh install acceptance`.

### 5. Local User Login

- **Preconditions:** ADMIN-created active local USER.
- **Steps:** Authenticate with local password; call `/auth/me`.
- **Expected Result:** Login succeeds as least-privileged `USER` with no role escalation.
- **Actual Result:** Created user authenticated and `/auth/me` returned `USER`.
- **Status:** **PASS**
- **Evidence:** FR steps 12–13; `backend/tests/integration/test_auth_and_mfa.py`.

### 6. LDAP Login

- **Preconditions:** Throwaway TLS-enabled OpenLDAP, enabled validated LDAP configuration and mapped directory user.
- **Steps:** Bind/search through OpenRBI; authenticate user via HTTP login; complete mandatory MFA when mapped privileged.
- **Expected Result:** Real directory credentials authenticate and JIT-provision/update the OpenRBI identity.
- **Actual Result:** TLS LDAP provider and HTTP login flows succeeded against the throwaway server.
- **Status:** **PASS**
- **Evidence:** CI `LDAP integration tests`; `scripts/run-ldap-integration-tests.sh`; `test_ldap_login_flow.py`.

### 7. LDAP Admin Mapping

- **Preconditions:** LDAP group DN mapped to `ADMIN` or `SECURITY_REVIEWER` in active runtime configuration.
- **Steps:** Login as group member; inspect role; repeat with admin-edited and case-varied DN mapping.
- **Expected Result:** Runtime mapping is authoritative, case-insensitive for DNs, and privileged MFA is enforced.
- **Actual Result:** Real login used saved mapping, produced expected role and enforced privileged MFA.
- **Status:** **PASS**
- **Evidence:** `test_admin_editable_group_role_mapping_is_used_at_real_login`; `test_group_role_mapping_is_case_insensitive_on_dn`.

### 8. LDAP Invalid Password

- **Preconditions:** Reachable LDAP and known directory username.
- **Steps:** Submit deliberately wrong password, then valid password after clearing the test lockout state.
- **Expected Result:** Wrong password returns generic invalid credentials and creates no authenticated session.
- **Actual Result:** Invalid attempts were denied; valid credentials still worked through the intended path.
- **Status:** **PASS**
- **Evidence:** `backend/tests/integration/test_ldap_login_flow.py`; CI `LDAP integration tests`.

### 9. LDAP Unavailable

- **Preconditions:** LDAP login configuration points to the test server, then that server is stopped.
- **Steps:** Attempt directory login while unreachable.
- **Expected Result:** Login is denied generically; no user session is issued and no exception details leak.
- **Actual Result:** The dedicated stopped-server HTTP run denied login.
- **Status:** **PASS**
- **Evidence:** `test_ldap_server_unreachable_denies_login_no_fallback`; `scripts/run-ldap-integration-tests.sh`.

### 10. LDAP Fail Closed

- **Preconditions:** LDAP outage and a same-named password-bearing local privileged identity collision fixture.
- **Steps:** Try directory credentials during outage and against the local identity; verify local credentials separately.
- **Expected Result:** No local fallback for an LDAP-only failure and no LDAP fallback into a local privileged row.
- **Actual Result:** Both directions were denied; only the authoritative local password authenticated the local row.
- **Status:** **PASS**
- **Evidence:** SR Privilege collision/LDAP rows; `test_ldap_login_flow.py`; `test_ldap_auth.py`.

## Browser isolation and network

### 11. Browser Session Launch

- **Preconditions:** Authenticated USER, online worker with free capacity, browser image present.
- **Steps:** `POST /sessions`; wait for display readiness; inspect DB and real managed container.
- **Expected Result:** Session reaches `ACTIVE` only after the hardened sandbox and display are ready.
- **Actual Result:** Real Firefox sandbox reached `ACTIVE` and was reachable through the display path.
- **Status:** **PASS**
- **Evidence:** FR step 14; `backend/tests/integration/test_policy_engine.py`; CI backend integration.

### 12. Browser Session Termination

- **Preconditions:** Owned active session and running sandbox.
- **Steps:** Terminate through user/admin API; inspect DB, audit and Docker inventory; repeat idempotently.
- **Expected Result:** DB is `TERMINATED`, `ended_at` is set, container is absent, event exists.
- **Actual Result:** API and admin-control tests removed real containers and recorded termination.
- **Status:** **PASS**
- **Evidence:** FR step 15; `test_admin_session_control.py`; `test_authorization.py`.

### 13. Public Internet from Sandbox

- **Preconditions:** Browser-plane isolation rules applied.
- **Steps:** Run a real container on browser-plane and request `http://example.com`.
- **Expected Result:** Public egress succeeds.
- **Actual Result:** Request completed while private/control destinations remained blocked.
- **Status:** **PASS**
- **Evidence:** `scripts/run-security-tests.sh` section 1; SR Sandbox network row.

### 14. RFC1918 Blocked

- **Preconditions:** Same isolated browser-plane.
- **Steps:** Attempt Postgres's actual container IP and arbitrary `10.0.0.1`.
- **Expected Result:** Connections fail within the bounded timeout.
- **Actual Result:** Both real and arbitrary RFC1918 targets were unreachable.
- **Status:** **PASS**
- **Evidence:** `scripts/run-security-tests.sh`; CI host-level security regression.

### 15. Link-local Blocked

- **Preconditions:** Same isolated browser-plane.
- **Steps:** Attempt a link-local destination from the sandbox network.
- **Expected Result:** Connection is denied by host enforcement.
- **Actual Result:** Link-local egress was blocked.
- **Status:** **PASS**
- **Evidence:** `scripts/run-security-tests.sh`; `scripts/setup-network-isolation.sh`; SR network row.

### 16. Metadata Endpoint Blocked

- **Preconditions:** Same isolated browser-plane.
- **Steps:** Request `169.254.169.254` from a sandbox-network container.
- **Expected Result:** Cloud metadata endpoint is unreachable.
- **Actual Result:** Request failed within timeout.
- **Status:** **PASS**
- **Evidence:** `scripts/run-security-tests.sh` metadata assertion.

### 17. Control Plane Blocked

- **Preconditions:** Backend, Agent, PostgreSQL, Valkey and ClamAV running on control-plane.
- **Steps:** Resolve their real container addresses and attempt each port from browser-plane; also probe peer VNC.
- **Expected Result:** All NEW sandbox-to-control/peer connections fail; backend-initiated display remains supported.
- **Actual Result:** API, Agent, DB, cache, scanner and peer sandbox were all unreachable from sandbox origin.
- **Status:** **PASS**
- **Evidence:** `scripts/run-security-tests.sh` sections 1 and 4; SR Sandbox network row.

## Files and quarantine

### 18. Benign Download

- **Preconditions:** Real ClamAV available and `AUTO_RELEASE` policy fixture.
- **Steps:** Submit benign bytes through the real scanning service; inspect SHA-256, scanner state, file state and audit.
- **Expected Result:** `CLEAN -> RELEASED` only after scan, with `FILE_RELEASED` evidence.
- **Actual Result:** Benign probe was clean and released with matching SHA-256/audit.
- **Status:** **PASS**
- **Evidence:** `scripts/security-release-review.py clean`; SR File download row.

### 19. Malicious/EICAR Download

- **Preconditions:** Real ClamAV and EICAR test payload.
- **Steps:** Scan through the same pipeline; inspect state, audit and incident.
- **Expected Result:** `INFECTED -> QUARANTINED`, malware event and critical incident; never released.
- **Actual Result:** ClamAV detected EICAR, quarantine held it and incident/audit were present.
- **Status:** **PASS**
- **Evidence:** `scripts/security-release-review.py eicar`; SR File download row.

### 20. Scanner Unavailable

- **Preconditions:** Otherwise releasable file fixture; ClamAV container stopped.
- **Steps:** Process file during outage; inspect DB status/events and absence of release.
- **Expected Result:** `ERROR -> QUARANTINED`, `DOWNLOAD_BLOCKED`, zero `FILE_RELEASED`.
- **Actual Result:** Fault run kept content quarantined and emitted no release.
- **Status:** **PASS**
- **Evidence:** FI ClamAV row; `scripts/security-release-review.py outage`.

### 21. Quarantine

- **Preconditions:** Policy requires review, scanner outcome is clean or unsafe/outage.
- **Steps:** Process content and list/view it through reviewer metadata endpoints.
- **Expected Result:** Metadata and opaque storage reference persist; no preview or user retrieval before release.
- **Actual Result:** Quarantined records remained held and reviewer APIs exposed metadata only.
- **Status:** **PASS**
- **Evidence:** SR Quarantine row; `test_authorization.py`; BR quarantine metadata/bytes checks.

### 22. Quarantine Release

- **Preconditions:** `QUARANTINED` clean file, authenticated `SECURITY_REVIEWER`; normal USER counter-check.
- **Steps:** POST reviewer comment to release; inspect reviewer/timestamp/comment/event; attempt second release and USER release.
- **Expected Result:** One audited `RELEASED` transition; duplicate is 409; USER is 403 and cannot mutate state.
- **Actual Result:** Real HTTP integration assertions passed with exactly one `FILE_RELEASED` event.
- **Status:** **PASS**
- **Evidence:** `backend/tests/integration/test_admin_quarantine.py`; release-token tests cover subsequent single-use retrieval.

## Worker and fault recovery

### 23. Worker Drain

- **Preconditions:** Online worker and existing active session.
- **Steps:** Drain; attempt new scheduling; verify existing container; inspect dashboard/audit; undrain.
- **Expected Result:** Existing session survives, new session gets 503/no capacity, state returns online, both actions audited.
- **Actual Result:** Drain round-trip preserved the active session and capacity with explicit warning/error.
- **Status:** **PASS**
- **Evidence:** FI Worker Drain row; `test_admin_nodes.py`.

### 24. Worker Maintenance

- **Preconditions:** Online worker and existing active session.
- **Steps:** Enter maintenance; refresh heartbeat; attempt scheduling; inspect warning/audit; leave maintenance.
- **Expected Result:** Heartbeat cannot undo maintenance; existing session survives; new scheduling is rejected.
- **Actual Result:** Maintenance persisted until explicit removal and capacity returned without loss.
- **Status:** **PASS**
- **Evidence:** FI Worker Maintenance row; `test_maintenance_is_not_undone_by_a_heartbeat_refresh`.

### 25. Browser Crash Reconciliation

- **Preconditions:** DB session `ACTIVE` with real running managed sandbox.
- **Steps:** `docker kill` sandbox; run grace cycles; inspect row/container/capacity/audit/dashboard.
- **Expected Result:** `FAILED` with `ended_at`; stopped container removed; lost-session event/warning; no ghost capacity.
- **Actual Result:** All state converged and the stopped-container resource was removed.
- **Status:** **PASS**
- **Evidence:** FI Browser Sandbox row; `test_lost_session_row_is_marked_failed_after_grace_period`.

### 26. Orphan Reconciliation

- **Preconditions:** Manually started managed sandbox with no DB row.
- **Steps:** Leave it running; execute two reconciliation cycles; inspect inventory, event and warning.
- **Expected Result:** Orphan is removed after grace and reported; no unnoticed container remains.
- **Actual Result:** Container disappeared, capacity returned, event and dashboard warning were present.
- **Status:** **PASS**
- **Evidence:** FI orphan row; `test_orphaned_container_is_terminated_after_grace_period`.

### 27. Session Agent Restart

- **Preconditions:** Active browser session and login token.
- **Steps:** Hard-kill Agent; observe fail-closed health/scheduling; start Agent; refresh state.
- **Expected Result:** Sandbox/DB session remain active, new scheduling is unavailable during uncertainty, capacity recovers exactly.
- **Actual Result:** Existing session stayed active; health degraded during outage and returned with unchanged capacity.
- **Status:** **PASS**
- **Evidence:** FI Session Agent row.

### 28. Backend Restart

- **Preconditions:** Active browser session and Redis login.
- **Steps:** `docker restart` backend; wait for liveness; re-query DB, Agent inventory, capacity and token.
- **Expected Result:** Durable/session-runtime state remains consistent and authentication survives.
- **Actual Result:** All assertions remained active/present after restart.
- **Status:** **PASS**
- **Evidence:** FI Backend row.

### 29. PostgreSQL Restart

- **Preconditions:** Persisted active session/user/audit state.
- **Steps:** Restart PostgreSQL; wait for `pg_isready`; retry application query after stale-pool invalidation.
- **Expected Result:** Persisted state returns unchanged; no ghost session or lost worker capacity.
- **Actual Result:** DB state, live container, login and capacity matched pre-restart observations.
- **Status:** **PASS**
- **Evidence:** FI PostgreSQL row.

### 30. Redis Restart

- **Preconditions:** Existing server-side login token plus DB/browser session.
- **Steps:** Restart Valkey container; query token, DB, Agent inventory and capacity.
- **Expected Result:** Controlled same-container restart preserves configured snapshot/auth state and does not affect browser state.
- **Actual Result:** Login token remained present and browser/DB/capacity were unchanged.
- **Status:** **PASS**
- **Evidence:** FI Redis/Valkey row.

## Operations and observability

### 31. Backup

- **Preconditions:** Current-schema Compact stack with identified user, policy, event, quarantine row and bytes.
- **Steps:** Run production backup; validate compressed DB and quarantine artifacts and baseline counts.
- **Expected Result:** Both artifacts are complete, non-empty and tied to recorded evidence.
- **Actual Result:** Backup gate emitted validated `ACCEPT BR-*` evidence before deliberate corruption.
- **Status:** **PASS**
- **Evidence:** BR steps 1–5; CI `Backup and restore acceptance`.

### 32. Restore

- **Preconditions:** Valid backup followed by deliberate DB and byte corruption.
- **Steps:** Run destructive confirmed restore; compare all table counts/IDs/bytes; perform login, sandbox and proxy smoke tests.
- **Expected Result:** Exact pre-corruption state and functionality return.
- **Actual Result:** Counts, records, bytes/SHA-256, login, sandbox, health and both portals matched baseline.
- **Status:** **PASS**
- **Evidence:** BR steps 6–10; CI `Backup and restore acceptance`.

### 33. Upgrade

- **Preconditions:** Pinned reproducible 0.1.1 commit with persistent seeded state and pre-upgrade backup.
- **Steps:** Replace all four images with target; run Alembic; verify identities, preserved data/secrets and live functional flows.
- **Expected Result:** One schema head, preserved state, changed images and working login/download/browser/health/proxy flows.
- **Actual Result:** Pinned-source upgrade completed with all persistent and functional assertions.
- **Status:** **PASS**
- **Evidence:** UP Automated procedure; CI `Upgrade acceptance`.

### 34. Audit Events

- **Preconditions:** Authentication, session, policy, file, worker and reconciliation actions exercised.
- **Steps:** Query append-only security events and assert action-specific types/metadata/RBAC; inspect secret absence.
- **Expected Result:** Security-relevant state changes are attributable and readable only by authorized reviewers, with no secrets.
- **Actual Result:** Integration/fault/security suites found the required events, including startup/lost/orphan and file outcomes.
- **Status:** **PASS**
- **Evidence:** SR audit/control matrix; FI audit column; `backend/tests/integration/` event assertions.

### 35. Health Dashboard

- **Preconditions:** ADMIN/SECURITY_REVIEWER and live worker/dependencies; injected degraded cases.
- **Steps:** Query aggregate health/dashboard; stop Agent/ClamAV and set worker modes; inspect components/KPIs/warnings/RBAC.
- **Expected Result:** Real metrics and independent component states, actionable warnings, no fabricated values, non-reviewer denied.
- **Actual Result:** Healthy and degraded paths reported real worker/capacity/dependency state and expected warnings.
- **Status:** **PASS**
- **Evidence:** `test_dashboard.py`; `test_admin_nodes.py`; FI warning column; FR step 16.

## Release decision

All 35 required scenarios have observable PASS evidence. This record does not
authorize a release from a different or failing commit: immediately before an
RC tag, confirm that the tag target is on `main`, its own `Release gates` check
is successful, P0 is zero, and no known P1 release blocker remains.
