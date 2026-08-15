# v1 Security Release Review

Date: 2026-08-15  
Scope: the real v1 candidate implementation after V1-010; targeted release review, not an architecture rewrite.

## Result

No known P0 security defect or P1 release blocker remains after this review. Two release-relevant findings were fixed:

1. A wrong password for an existing password-bearing local identity could fall through to LDAP. A same-named directory identity could therefore authenticate into the local row and retain its locally assigned role. Local password-bearing identities are now authoritative; LDAP fallback remains available only for unknown or LDAP-only (`password_hash IS NULL`) identities. A real LDAP collision regression test covers the privileged case.
2. The deployment guide described an expiring first-run token, but the persisted token had no time limit. Its issuance time is now stored and checked against `OPENRBI_SETUP_TOKEN_TTL_SECONDS` (30 minutes by default). Restarting an uninitialized backend still invalidates the old token and issues a fresh one.

## Control matrix

| Area | Real checks and evidence | Result |
|---|---|---|
| Local password hashing | Argon2 creation/verification, malformed hashes fail closed, bootstrap and normal login use the same implementation | PASS |
| Session cookies | Central policy verifies `Secure` outside development, `HttpOnly`, `SameSite=Lax`, `/` path and configured max-age; Redis expiry returns generic 401 | PASS |
| Login lockout | Ten failed local or LDAP attempts lock the username; correct credentials remain blocked; lockout event recorded | PASS |
| MFA/recovery/reset | Mandatory for ADMIN and SECURITY_REVIEWER, TOTP encrypted, recovery codes hashed and single-use, reset revokes sessions and writes audit | PASS |
| LDAP | LDAPS/StartTLS validation, escaped filters, runtime group mapping, case-insensitive DN normalization, outage and invalid password fail closed | PASS |
| Privilege collision | Same-named LDAP password cannot enter a password-bearing local ADMIN; disabled LDAP identities cannot receive a session | PASS |
| Bootstrap | Random console-only token, Argon2 hash only, 30-minute persisted TTL, rate limit, restart invalidation, permanent closure after initialization | PASS |
| IDOR/session ownership | Other users and normal-surface admins receive indistinguishable 404 for detail, terminate, upload, file listing/token operations; download tokens bind to issuer | PASS |
| Sandbox runtime | Live container is UID 10001, unprivileged, read-only, `cap_drop: ALL`, `no-new-privileges`, bounded, and has neither Docker socket nor quarantine mount | PASS |
| Sandbox network | Public internet allowed; RFC1918, link-local/metadata, Docker networks, backend/admin API, PostgreSQL, Redis, Session Agent and peer sandboxes blocked | PASS |
| IPv6 | Browser network has IPv6 disabled and is asserted by the live host gate, preventing an unfiltered IPv6 bypass | PASS |
| File download | Live benign scan produces CLEAN/RELEASED with SHA-256; real EICAR produces INFECTED/QUARANTINED plus incident; stopped ClamAV produces ERROR/QUARANTINED and no release event | PASS |
| File upload | Ownership, size cap, magic MIME, SHA-256, policy, scan-before-write, benign write, malware incident and scanner-outage no-write branches are tested | PASS |
| Quarantine | Release/reject RBAC, single-use user-bound release tokens, retention, backup/restore bytes and upgrade persistence are covered | PASS |
| Secrets | Startup rejects missing/example secrets; LDAP responses structurally omit bind passwords; TOTP rotation re-encrypts; gitleaks found no leak in 140 commits | PASS |
| Frontend | Cookie-only authentication, no client auth-token storage, no raw HTML rendering, LDAP secret omitted, production bundle rejects backend secret identifiers | PASS |

## Reproducible evidence

- `backend/tests/integration/test_auth_and_mfa.py`
- `backend/tests/integration/test_authorization.py`
- `backend/tests/integration/test_ldap_login_flow.py`
- `backend/tests/integration/test_setup.py`
- `backend/tests/integration/test_upload_security.py`
- `scripts/run-security-tests.sh`
- `scripts/security-release-review.py`
- `.github/workflows/ci.yml` (`Backend integration tests`, `LDAP integration tests`, `Secret scan (gitleaks)`, and aggregate `Release gates`)

Local review evidence on 2026-08-15:

- Auth/setup/ownership subset: 29 passed.
- Upload security subset: 3 passed.
- Live file probes: CLEAN/RELEASED; EICAR INFECTED/QUARANTINED with incident; scanner outage ERROR/QUARANTINED with `DOWNLOAD_BLOCKED`.
- Alembic: single head `e7a4c2d91b60`; upgrade from `d5e8a13c6f92` succeeded.
- Gitleaks 8.28.0: 140 commits, approximately 2.78 MB, no leaks found.

The PR CI run is the authoritative Linux-host evidence for firewall and sandbox-runtime assertions.

## Residual risks (not release blockers)

- Compact mode deliberately exposes user and admin portals on one origin. Production operators requiring management-plane separation must use the documented Segmented profile and external network controls.
- Sandbox VNC has no independent password and relies on the tested browser-plane firewall plus backend ownership checks. A per-session VNC credential remains defense-in-depth work for a later release.
- Blocked sandbox packets are kernel-logged with `openrbi-blocked:` but are not yet ingested as application `NETWORK_ACCESS_BLOCKED` events. This affects centralized audit convenience, not enforcement.
- Browser-plane IPv6 is disabled instead of maintaining an equivalent IPv6 allow/block policy. Enabling IPv6 without a reviewed policy is unsupported.
