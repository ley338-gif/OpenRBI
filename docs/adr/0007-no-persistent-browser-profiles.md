# ADR 0007: No persistent browser profiles in MVP 1

## Status

Accepted

## Context

Persistent browser profiles (saved logins, cookies, history, bookmarks across sessions) are a common RBI feature request, but they turn each browser container into a store of potentially sensitive user data that must then be protected, backed up, encrypted at rest, and access-controlled per user — a significant scope and risk expansion for MVP 1.

## Decision

Every browser session gets a fresh, temporary profile created at session start and destroyed at session end, with no cross-session persistence of cookies, history, saved passwords, or local storage. This is enforced by the browser container's own temporary profile path (see [docs/security-model.md](../security-model.md)), not merely a UI setting.

## Alternatives Considered

- **Persistent profile per user, mounted per session** — desirable UX (users don't re-login to every site every session), but requires per-user encrypted profile storage, a data-retention/deletion policy, and profile-mount isolation guarantees between concurrent/former sessions — explicitly listed as out of MVP 1 scope.
- **Persistent profile shared across a group** — rejected outright: violates the "no shared writable browser profiles" constraint and creates cross-user data leakage risk.

## Consequences

Users must re-authenticate to websites each session, which is a real UX cost accepted deliberately for MVP 1. This also means OpenRBI stores meaningfully less sensitive data at rest, shrinking the impact of a quarantine-storage or host compromise, and removing an entire class of cross-session data-leak bugs from MVP 1's threat surface.
