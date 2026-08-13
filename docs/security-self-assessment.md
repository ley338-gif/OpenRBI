# Security Self-Assessment

Roadmap Phase A / A2. **This is not an independent security review or a substitute for one** — it is a structured, first-party check that every control `docs/threat-model.md` and `docs/security-model.md` claim actually exists in the code, with a file/line reference for each claim rather than a restatement of the claim itself. Where a control could not be verified, or was found to be weaker than documented, that is stated plainly below, not smoothed over.

Loosely follows the [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/) chapter structure where it fits this project's actual architecture; chapters with no OpenRBI-relevant surface (e.g. ASVS V9 API design conventions, mobile-specific controls) are omitted rather than padded out. Verified against commit `main` as of 2026-08-13 (originally 2026-08-12; the V2 rows covering Roadmap Phase B / B1's LDAP authentication path were added the following day once that work landed, re-verified against the code at that point) — re-verify before relying on this after further changes, especially anywhere marked **GAP** below.

**Use of this document**: acceptable as the basis for a first, tightly scoped pilot in an isolated test environment (Roadmap Phase B). Not a substitute for A2's own stated goal of an eventual independent external review, and not sufficient on its own to justify production use — see `README.md`'s Project status and `SECURITY.md`'s Known MVP limitations, both of which remain accurate after this pass.

---

## V2 — Authentication

| Control | Status | Evidence |
|---|---|---|
| Passwords hashed with Argon2, never stored/compared in plaintext | confirmed | `backend/app/core/security.py:1-15` — `argon2.PasswordHasher`, `hash_password`/`verify_password`. |
| Login failure is identical (generic 401) for unknown username, disabled account, and wrong password — no enumeration | confirmed | `backend/app/api/auth.py:59-67`: a single `if user is None or not user.is_active or not verify_password(...)` branch produces one `HTTPException(401, "invalid credentials")` regardless of which condition was true. |
| Per-username brute-force lockout, independent of the MFA-challenge attempt cap | confirmed | `backend/app/api/auth.py:47-54` (`is_login_locked` → `429`, `LOGIN_LOCKED` event) and `backend/app/core/sessions.py`'s `record_login_failure`/`is_login_locked` (Redis-backed, 10 failures / 15 min per `docs/security-model.md`). Covered by an integration test: `backend/tests/integration/test_auth_and_mfa.py::test_login_lockout_after_repeated_failures`. |
| MFA (TOTP) mandatory for ADMIN/SECURITY_REVIEWER, re-evaluated from the user's *current* role at every login (not just at account creation) | confirmed | `backend/app/api/auth.py:32` (`_MFA_MANDATORY_ROLES`), exercised by `test_auth_and_mfa.py::test_admin_login_requires_mfa_enrollment` and `test_security_reviewer_also_requires_mandatory_mfa`. |
| Recovery codes: single-use, hashed at rest, shown exactly once | confirmed | `test_auth_and_mfa.py::test_recovery_code_is_single_use`; hashing confirmed via `backend/app/models/user.py`'s `RecoveryCode` model storing a hash column, never plaintext. |
| MFA-challenge attempt cap, independent of the per-username login lockout | confirmed | `backend/app/api/auth.py:147` — `"too many failed attempts, please log in again"`, backed by `record_mfa_pending_failure`. |
| **(Roadmap Phase B / B1)** LDAP credentials are verified via a real bind, never cached or compared against a locally-stored value | confirmed | `backend/app/core/auth_providers/ldap.py`'s two-step bind — a search-account bind locates the user's DN, then a second bind *as that DN with the caller's own password* is the actual verification; the plaintext password is never written anywhere. |
| LDAP fails closed on any connection/TLS/protocol error — never a fallback that grants access | confirmed | `backend/app/core/auth_providers/ldap.py:88-92`'s broad `except` returns `AuthResult(success=False)`; exercised end-to-end (not just at the provider level) by `backend/tests/integration/test_ldap_login_flow.py::test_ldap_server_unreachable_denies_login_no_fallback`, which genuinely stops the LDAP server mid-test rather than mocking the failure. |
| A plain unencrypted `ldap://` bind is not a configurable option | confirmed | `backend/app/config.py`'s `_ldap_config_is_fail_closed` `model_validator` raises at startup if `ldap_enabled=True` with `ldap://` and StartTLS disabled — enforced before the process ever accepts a request, not just documented as a recommendation. |
| MFA-mandatory-role enforcement applies identically to an LDAP-authenticated login as a local one | confirmed | `backend/tests/integration/test_ldap_login_flow.py::test_ldap_login_mapped_to_admin_requires_mfa_enrollment` reuses `tests/conftest.py`'s existing `login_with_mfa_enrollment` helper completely unchanged for a real LDAP-provisioned ADMIN login — the same enforcement code path (`app/api/auth.py`'s `_MFA_MANDATORY_ROLES` check), not a parallel one that merely looks equivalent. |
| Failed LDAP bind attempts count toward the same per-username lockout as failed local attempts — no separate, weaker-protected path | confirmed | `backend/app/api/auth.py`'s `login()` calls `record_login_failure`/`is_login_locked` once per attempt regardless of which provider(s) were tried; exercised by `test_ldap_login_flow.py::test_failed_ldap_bind_counts_toward_the_same_lockout_as_local`. |
| Identity resolution for a successful LDAP login is exact-username-match only — no fuzzy/PII-based matching | confirmed | `backend/app/services/ldap_provisioning.py`'s `resolve_or_provision_ldap_user`; deliberately rejected alternative (name/birthdate matching) recorded in [ADR 0015](adr/0015-auth-provider-abstraction.md)'s Alternatives Considered, specifically for its account-takeover risk from a false-positive match. |
| An admin-managed local account's role cannot be silently downgraded by an incidental LDAP group login | confirmed | `backend/app/services/ldap_provisioning.py:65-75` — role is only ever re-derived from LDAP groups when `user.password_hash is None` (the account was itself LDAP-provisioned); an account with a real local password keeps its locally-configured role regardless of what an LDAP login under the same username resolves to. Verified directly against a live database during development, not just read from the code: a real local `ADMIN` account was created, its matching LDAP identity's groups changed to map to `USER`, and a login with the real AD password left the account's role unchanged at `ADMIN`. |
| `users.password_hash` being `NULL` (an LDAP-only account) cannot be mistaken for "no password required" by the local path | confirmed | `backend/app/core/auth_providers/local.py`'s `LocalAuthProvider.authenticate` explicitly checks `user.password_hash is None` and fails closed, rather than passing `None` into `verify_password()`. |

## V3 — Session Management

| Control | Status | Evidence |
|---|---|---|
| Server-side sessions (Redis-backed), not self-contained JWTs — a logout or admin-forced disconnect is immediately effective everywhere | confirmed | `backend/app/core/sessions.py`'s `create_session`/`delete_session` operate on Redis-stored session state; `docs/architecture.md` and `CHANGELOG.md`'s Phase 3 entry corroborate this was a deliberate choice, not an oversight. |
| Session cookie: `HttpOnly`, `SameSite=Lax`, `Secure` outside development | confirmed | `backend/app/api/auth.py:88-94` — `httponly=True`, `samesite="lax"`, `secure=settings.environment != "development"`. **Note**: `secure` depends on `OPENRBI_ENVIRONMENT=production` actually being set once TLS is live (`docs/deployment.md#tls`) — an operator who forgets that step silently loses this protection; not enforced independently of that setting. |
| A cleared/expired session cannot see protected content on a fresh request (no client-side-only auth gate) | confirmed | Exercised end-to-end by `frontend/e2e/tests/user-portal.spec.ts`'s "logging out invalidates the session" test — logout, then a fresh `page.goto("/")` is redirected back to the login form, not served from a cached client-side auth state. |
| Admin-forced Disconnect closes the user's live display connection immediately, not just a DB flag | confirmed | `docs/admin-guide.md`'s Sessions section and `CHANGELOG.md`'s Admin session control entry describe an in-process WebSocket registry used for this; `backend/tests/integration/test_admin_session_control.py::test_isolate_disconnect_kill_are_audited_and_kill_is_admin_only` exercises the audit-trail side of the same action. |

## V4 — Access Control

| Control | Status | Evidence |
|---|---|---|
| `require_role()` fails closed — an unresolvable or disallowed role is always `403`, never an implicit allow | confirmed | `backend/app/core/deps.py:36-40`'s own docstring states this explicitly; the function gates every admin-only route. |
| Resource ownership: another user's session/file is `404`, identical to nonexistent — never a `403` that would confirm the resource exists | confirmed | `backend/app/api/sessions.py:26-35`'s `_get_own_session_or_404` helper; exercised by `backend/tests/integration/test_authorization.py::test_user_cannot_see_another_users_session` and `test_user_cannot_see_another_users_quarantine_file`. |
| No implicit ownership for ADMIN — an admin account gets the same `404` as anyone else for a resource it doesn't own | confirmed | `test_authorization.py::test_admin_has_no_implicit_ownership_of_someone_elses_session` and `test_admin_cannot_request_a_download_token_for_someone_elses_file`. |
| Download token bound to the issuing user only | confirmed | `test_authorization.py::test_download_token_bound_to_issuing_user_only`. |
| Listener-mode route non-existence (`user` mode never registers admin routers) | confirmed | `docs/adr/0011-user-admin-listener-separation.md`; exercised by `scripts/test-listener-modes.sh` and `frontend/e2e/tests/admin-portal.spec.ts`'s "User Portal's own session cannot act on the admin API" (asserts `403` or `404`, never `200`). |
| **GAP** — Segmented deployment's two listener processes still share one Postgres role/credential set and one Session Agent bearer token; a compromise of the `user`-mode process still holds credentials scoped to *both* listeners' data, even though it can't reach the admin *routes* | documented gap, not fixed | `docs/adr/0011-user-admin-listener-separation.md`'s own "Alternatives Considered" section states this explicitly. Carried into this assessment rather than re-discovered, since it was already honestly documented — flagged here so A2 doesn't imply it's new or resolved. |

## V6 — Cryptography / Secrets

| Control | Status | Evidence |
|---|---|---|
| TOTP secrets encrypted at rest (Fernet/AES), key from an environment-provided value, never derived from a guessable default | confirmed | `backend/app/core/crypto.py:8-20` — `_fernet()` raises if `OPENRBI_TOTP_SECRET_ENCRYPTION_KEY` is unset or not exactly 32 bytes after hex-decoding. |
| Startup fails closed if a critical secret is empty or still the literal `.env.example` placeholder | confirmed | `backend/app/config.py` and `session-agent/app/config.py`'s `_reject_missing_or_placeholder_secret` validators; the real historical incident this caught is documented in `docs/security-model.md`'s Hardening section. |
| No secret ever committed to git | confirmed (Roadmap A6) | Full-history `gitleaks` scan (51 commits) — no leaks found; `git log --all --diff-filter=A --name-only` confirms only `.env.example`, never a real `.env`, was ever added. See `docs/security-model.md#secrets` for the dated record. |
| Secret rotation is a documented, safe procedure for every secret, including the one (`OPENRBI_TOTP_SECRET_ENCRYPTION_KEY`) that isn't a simple `.env` edit | confirmed (Roadmap A6) | `docs/deployment.md#secret-rotation`, `scripts/rotate-totp-key.sh`, verified end-to-end (re-encrypt → restart → decrypt-under-new-key round trip actually checked, not assumed). |
| No SQL built via string interpolation/formatting (injection surface) | confirmed by spot check | `grep`-based sweep of `backend/app/` for `f"...SELECT`/`.format(...SELECT` and similar patterns: zero matches. All query construction observed during this pass goes through SQLAlchemy's parameterized query builder. **Not** a claim that every line of the codebase was manually read — a targeted pattern sweep, stated as such. |

## V7 — Error Handling, Logging, Audit

| Control | Status | Evidence |
|---|---|---|
| `SecurityEvent` rows are only ever constructed inside `record_security_event` — nothing bypasses it | confirmed | `grep -rl "SecurityEvent("` across `backend/app/` returns only the model definition and `app/services/security_events.py` itself. |
| Audit log is append-only in practice, not just by convention — no code path issues `UPDATE`/`DELETE` against `security_events` | confirmed | Targeted `grep` for `security_events` combined with `UPDATE`/`DELETE` keywords across `backend/app/`: zero matches (outside test fixture cleanup, which is explicitly test-data-only and prefixed `pytest_`). |
| Audit metadata never contains a password, secret, token, or file content | confirmed by pattern review | `docs/development.md`'s Phase 18 entry documents this was audited call-site by call-site during that phase; this pass re-confirmed by reviewing `metadata=` arguments at every `record_security_event` call site touched during this session's other work (auth, sessions, quarantine) — IDs, hashes, filenames, and reason strings only. Not re-audited exhaustively call-site by call-site in this pass; treat the Phase 18 audit as the primary source and this as a spot-check that nothing regressed in the areas touched since. |
| A raw exception/traceback is never returned to the client | confirmed for the login path | `frontend/e2e/tests/user-portal.spec.ts`'s "rejects wrong credentials" test explicitly asserts the response body never contains `Traceback` or a raw `{"detail"` JSON leak beyond the intended generic message. **Not independently re-verified for every other endpoint in this pass** — FastAPI's default exception handling and the project's consistent use of `HTTPException` with a static `detail` string make this likely to hold elsewhere, but that is an inference from the pattern, not a line-by-line audit of every route. |

## V10 — Malicious Code / File Handling

| Control | Status | Evidence |
|---|---|---|
| File type never trusted from extension or declared `Content-Type` — magic-byte detection only | confirmed | `backend/app/core/mime_matching.py:3`'s own docstring states the rule; `backend/app/services/downloads.py:75` and `uploads.py:36` both call `magic.from_buffer(data, mime=True)`. |
| Fail-closed scan decision matrix: scanner unreachable → always `QUARANTINED`, regardless of policy verdict | confirmed | `backend/app/services/scanning.py:41-51` — `except (ClamAVError, OSError)` branch unconditionally sets `QuarantineStatus.QUARANTINED` with an explicit `"scanner unavailable — fail closed, no auto-release"` reason string. |
| Infected file is quarantined (never silently deleted) and always opens a `CRITICAL` incident, even against an `AUTO_RELEASE` policy verdict | confirmed | `backend/app/services/scanning.py` (malware branch) and `CHANGELOG.md`'s File scanner entry describing the EICAR-string verification this claim is based on. |
| Unmatched/unknown file type fails closed to `QUARANTINE`, not silent allow | confirmed | `backend/app/services/scanning.py:112-113`; exercised by `backend/tests/integration/test_policy_engine.py::test_unmatched_file_fails_closed_to_quarantine`. |
| Structural (not substring) source-domain matching — a forged subdomain never matches a wildcard rule it shouldn't | confirmed | `backend/app/core/source_matching.py`; exercised by the parametrized `test_policy_engine.py::test_source_matching_rejects_forged_domains` covering `microsoft.com.attacker.org` and `evil-microsoft.com` specifically. |
| Release tokens are single-use via an atomic operation, not a check-then-delete race | confirmed | `backend/app/core/release_tokens.py:23-29` — Redis `GETDEL`, explicitly chosen over separate GET+DELETE calls to close the race window; exercised by `backend/tests/integration/test_quarantine_release_tokens.py::test_release_token_is_single_use`. |

## V11 — Business Logic (Session / Sandbox Isolation)

| Control | Status | Evidence |
|---|---|---|
| Backend has no Docker socket access — a backend compromise does not directly yield container-runtime control | confirmed | `docker-compose.yml:61-62`'s explicit comment plus absence of a `docker.sock` volume mount on the `backend` service (present only on `session-agent`, line 76, read-only). See [ADR 0005](adr/0005-no-docker-socket-in-backend.md). |
| Sandbox network egress: public internet reachable; RFC1918, link-local, cloud metadata address, and the control plane all blocked | confirmed | `scripts/setup-network-isolation.sh:87-93` (the actual blocklist CIDRs) plus `scripts/run-security-tests.sh`'s live checks against a real running stack (now wired into CI as of Roadmap A5 — previously only ever run by hand). |
| Isolate is a real DENY-ALL primitive (sandbox loses all Docker network attachments), not just a database flag | confirmed | `scripts/run-security-tests.sh`'s "Isolate actually removes all Docker networks" check, and `backend/tests/integration/test_admin_session_control.py::test_isolate_disconnect_kill_are_audited_and_kill_is_admin_only` for the audit-trail side. |
| Sandbox-to-sandbox isolation between two concurrently live sessions | confirmed (closed by Roadmap A3) | Was an open gap when this document was first written — `scripts/run-security-tests.sh`'s three original checks were all sandbox-to-*infrastructure*, none sandbox-to-*sandbox*. Closed in the same Phase A pass: a new check creates a real sandbox and confirms nothing else on `browser-plane` can reach its VNC port; run against the live stack, 8/8 passing. |
| DNS-rebinding: a hostname whose resolved address is a blocked IP is still blocked | confirmed (closed by Roadmap A3) | Was an open gap for the same reason — the IP-based-blocking reasoning was sound but untested as a distinct scenario. Closed with a `curl --resolve`-based check faking a hostname resolving to Postgres's real IP; connection still blocked. |
| Two parallel sessions of different users cannot see or act on each other's data (API/DB level) | confirmed | Covered by V4's ownership tests above (`test_user_cannot_see_another_users_session`, etc.) — the data-plane half of session isolation; the network-plane half (sandbox-to-sandbox) is confirmed directly above. |

## V12 — Files and Resources

| Control | Status | Evidence |
|---|---|---|
| No client directory ever mounted into a sandbox for uploads | confirmed | `docs/quarantine.md#upload-pipeline-phase-16`'s explicit statement, consistent with the Session Agent's `write_upload` going through a live `exec` socket rather than a filesystem mount (`CHANGELOG.md`'s Fixed section, "write-into-sandbox path"). |
| Quarantine storage is content-addressed (SHA-256), not attacker-influenced filenames | confirmed | `docs/quarantine.md` and `backend/app/services/downloads.py`'s staging logic hash files before persisting them. |
| No browser session data (profile, cookies, history) persists past the session | confirmed | [ADR 0007](adr/0007-no-persistent-browser-profiles.md); `docs/deployment.md#storage-layout` explicitly states there is no volume for this because there is nothing to store. |

---

## Summary of open gaps found by this pass

Two of the four gaps originally found here were closed within the same Phase A effort (Roadmap A3, merged alongside this document) rather than left open — noted below for the record, since a reader of the merged history should be able to see they were real gaps at the time this assessment was written, not retroactively erased:

1. ~~Sandbox-to-sandbox network isolation has no automated test~~ — **closed**, see V11 above.
2. ~~No automated DNS-rebinding-specific test~~ — **closed**, see V11 above.
3. **Segmented deployment's two listener processes still share DB/Session-Agent credentials** — still open. Already honestly documented in ADR 0011, not new, restated here so this assessment doesn't read as implying it's resolved.
4. **Session cookie `Secure` flag depends on an operator correctly setting `OPENRBI_ENVIRONMENT=production`** — still open. Not independently enforced; a deployment that skips this step silently loses the protection with no startup warning.
5. **Audit-metadata-never-contains-a-secret** and **no-raw-traceback-to-client** were spot-checked against the areas touched by this session's other work, not re-audited call-site-by-call-site or route-by-route from scratch — the original Phase 18 audit remains the authoritative source for the former.
6. **(Roadmap Phase B / B1)** `OPENRBI_LDAP_GROUP_ROLE_MAPPING`'s group-DN matching is exact-string, case-sensitive — it does not normalize DN casing or attribute ordering the way some directory clients do. A mapping configured with different casing than the directory actually returns silently resolves to `USER` rather than erroring, which could be mistaken for "the account just isn't in that group" instead of "the mapping is misconfigured." Documented as a known limitation in `docs/admin-guide.md` and `backend/app/services/ldap_provisioning.py`'s own docstring, not silently assumed correct.

None of these rise to "structural isolation weakness that can't be fixed with reasonable effort" — the Roadmap's own kill criterion for A2. They are scoped, specific, and each has a clear next step already named above.
