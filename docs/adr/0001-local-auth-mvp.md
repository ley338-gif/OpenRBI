# ADR 0001: Local username/password authentication for MVP 1

## Status

Accepted

## Context

OpenRBI needs an authentication mechanism for both the admin and user portals. Enterprise deployments will eventually want LDAP/Active Directory, Entra ID, OIDC, or SAML federation. Building all of these in MVP 1 would delay a working end-to-end system and adds attack surface (federation metadata parsing, external IdP trust) before the core isolation platform itself is proven.

## Decision

MVP 1 implements only local authentication: usernames + passwords (hashed with a memory-hard KDF, e.g. Argon2id) stored in PostgreSQL, plus mandatory TOTP MFA for ADMIN and SECURITY_REVIEWER roles (see [ADR 0002](0002-totp-mfa.md)). Users are referenced internally by stable UUIDs, never by username, so a future identity-federation layer can be added without a primary-key migration.

## Alternatives Considered

- **OIDC/SAML from day one** — correct long-term direction, but pulls in external IdP trust configuration and federation edge cases before the RBI core (sandboxing, isolation, policy engine) is validated. Explicitly out of scope for MVP 1 per the project's scope boundary.
- **LDAP/AD bind only** — still requires an external directory to test against and doesn't remove the need for local accounts (e.g. a break-glass admin), so it doesn't reduce MVP complexity as much as it appears to.

## Consequences

Local auth is fully sufficient for the MVP 1 Definition of Done (Thomas/Admin walkthrough) and keeps credential storage entirely under OpenRBI's control, which simplifies audit event generation (`USER_LOGIN`, `USER_LOGIN_FAILED`). Adding federated identity later requires a new auth provider abstraction and account-linking flow, which is intentionally deferred rather than half-built now.
