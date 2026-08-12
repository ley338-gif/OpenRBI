# ADR 0002: TOTP for multi-factor authentication

## Status

Accepted

## Context

MFA is mandatory for ADMIN and SECURITY_REVIEWER accounts, and available to all users. WebAuthn/FIDO2 is the stronger long-term choice (phishing-resistant) but is explicitly out of MVP 1 scope, and SMS/email OTP requires an external delivery dependency (SMS gateway, outbound mail) that OpenRBI, as a self-hosted platform with no assumed internet-facing mail relay, cannot assume is configured.

## Decision

MVP 1 implements TOTP (RFC 6238) as the sole MFA factor: QR-code enrollment, TOTP verification at login, and one-time-use recovery codes for account recovery. TOTP secrets are stored encrypted at rest (application-layer encryption, not just relying on disk/DB encryption). Recovery codes are stored only as hashes and are shown to the user exactly once at generation time. An admin-initiated MFA reset is always logged as a security event (`MFA_RESET`).

## Alternatives Considered

- **WebAuthn/FIDO2** — stronger phishing resistance, but explicitly deferred per the project's MVP scope boundary; revisit post-MVP.
- **SMS/email OTP** — introduces an external delivery dependency and weaker security properties (SIM swap, mail account compromise); doesn't fit a self-hosted platform with no guaranteed outbound mail/SMS integration.

## Consequences

TOTP requires no external service dependency, which fits a self-hosted deployment model. It does mean MVP 1 offers no phishing-resistant factor; this is documented as a known limitation in [docs/threat-model.md](../threat-model.md). Recovery-code handling (single display, hashed storage, single-use invalidation) must be enforced server-side, not just hidden in the UI.
