# ADR 0015: AuthProvider abstraction for local + LDAP authentication

## Status

Accepted

## Context

Roadmap Phase B / B1 adds LDAP/LDAPS bind authentication against an existing Active Directory as an equal, parallel option alongside the existing local (Argon2-hashed password) login — not a replacement. Before this change, `/auth/login` (`app/api/auth.py`) verified credentials entirely inline: a direct `SELECT` against `users` followed by `verify_password()` against the stored Argon2 hash. There was no seam to add a second verification method without either duplicating the surrounding logic (login lockout, MFA enforcement, audit events, session issuance) or entangling it with the local path's specifics.

This mirrors the exact problem `SandboxProvider`/`DisplayProvider`/`BrowserProvider`/`FileScanner` already solved for infrastructure backends (ADR 0003) — MVP 1 commits to one concrete mechanism but the project's own stated direction is to support more later without rewriting core logic.

## Decision

Introduce an `AuthProvider` protocol (`backend/app/core/auth_providers/base.py`), following the same pattern as `SandboxProvider`: a `typing.Protocol` with `authenticate(db, username, password) -> AuthResult` and `health() -> bool`, plus a `factory.py` seam (`get_local_auth_provider()`, mirroring `session-agent/app/providers/factory.py`'s `get_provider()`).

`AuthResult` is deliberately narrow: `success`, the resolved `username`, and `matched_user_id` (set whenever a provider found an existing local `User` row, even on failure — preserves the pre-existing behavior of attaching a `user_id` to a failed-login audit event for a disabled account or wrong password, vs. leaving it null for a genuinely unknown username). Everything downstream of that — MFA enforcement (`_MFA_MANDATORY_ROLES`), login lockout (`is_login_locked`/`record_login_failure`, Redis-keyed by username, method-agnostic), session issuance, and audit events — already operates on the resolved `User`/`Role` row, not on *how* the credential was verified. It stays exactly where it already lived in `login()`, unchanged, and applies identically regardless of which provider authenticated the request.

`LocalAuthProvider` (`local.py`) is the first, required implementation — a pure move of the pre-existing inline logic, not a rewrite. `LdapAuthProvider` (Roadmap B1.2, this ADR's companion decision below) is the second.

### Fail-closed on LDAP unavailability (decided here, implemented in B1.2)

An LDAP server that is unreachable or fails TLS negotiation must result in a denied login for LDAP-mapped accounts, **never** a silent fallback to some other outcome that grants access. This is the same fail-closed principle already applied to the malware scanner and policy engine (ADR 0008) — an unavailable security-relevant dependency must never be interpreted as "allow." Concretely: `LdapAuthProvider.authenticate()` catches connection/TLS errors and returns `AuthResult(success=False)`, indistinguishable from a wrong password to the caller. Local login remains available throughout an LDAP outage — this is *why* local login is never disabled or deprioritized, not an oversight (see also Roadmap B1's explicit requirement that local stays as the admin/emergency path).

### Identity resolution: exact-match reconciliation, no fuzzy matching

A successful LDAP bind for username `X` is resolved against local `users.username` by **exact string match only**. If a local account with that exact username already exists, it is authenticated via this LDAP login going forward (its role/group mapping is re-derived from the LDAP bind's group memberships on every successful login — the same "recompute from source of truth at every login" principle the codebase already applies to MFA-mandatory-role re-evaluation). If no local account exists, one is JIT-provisioned.

Explicitly rejected: matching on name/first name/date of birth in addition to or instead of username. That would require storing new PII (`first_name`, `last_name`, `date_of_birth` don't exist on `User` today) with real GDPR handling implications, and a fuzzy or multi-field match is inherently more error-prone than an exact username match — a false-positive match links the wrong local account to a different real-world identity, which is a direct account-takeover path against `threat-model.md`'s "User credentials" and "Session tokens" assets. Exact-match-only has no such failure mode: two different usernames never collide, and there is nothing to get subtly wrong.

### `users.password_hash` becomes nullable

A JIT-provisioned LDAP-only user has no local password to store — LDAP credentials are never cached locally (Roadmap B1's explicit prohibition). Making `password_hash` nullable and having `LocalAuthProvider` explicitly reject a `NULL` hash (rather than storing an unusable placeholder value that could be mistaken for a real hash) is the cleaner of the two options considered: no magic sentinel value anywhere in the schema that a future reader has to know is intentionally broken.

## Alternatives Considered

- **A second `if`-branch inline in `login()` for LDAP, no interface** — fastest to write, but couples the route handler to two vendor-specific verification mechanisms directly, makes local-only unit testing of the MFA/lockout/session logic require either a real LDAP server or ad hoc mocking, and doesn't match this project's own established provider pattern for exactly this kind of "one required mechanism today, more later" problem.
- **Try every configured provider in a fixed order per login attempt** (e.g. always try local first, fall back to LDAP) — rejected in favor of exact-username-match resolution: trying multiple providers blind creates timing-oracle and enumeration surface (a response that took long enough to also attempt an LDAP bind reveals the account isn't local), and doesn't answer the harder question of *which* provider is authoritative for a given username once both could plausibly match.
- **Placeholder/unusable password hash for JIT-provisioned users** instead of a nullable column — rejected as described above (Decision section).
- **Fuzzy/multi-field identity matching** (name, birth date) — rejected as described above (Decision section); considered and explicitly declined after discussion, not merely unconsidered.

## Consequences

Adds an interface layer (`backend/app/core/auth_providers/`) and one nullable-column migration (`users.password_hash`), but keeps local and LDAP authentication as independently testable, swappable modules with a single, unchanged enforcement point for MFA/lockout/audit. `LocalAuthProvider`'s behavior is verified unchanged by the full pre-existing `backend/tests/integration/test_auth_and_mfa.py` suite passing without modification (Roadmap B1.1). Follow-up: `LdapAuthProvider` itself, group→role mapping, and the reconciliation/JIT-provisioning logic are Roadmap B1.2–B1.5, tracked as separate PRs per the roadmap's own scope discipline.
