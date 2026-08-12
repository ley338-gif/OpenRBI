# ADR 0008: Fail closed on every security-relevant dependency failure

## Status

Accepted

## Context

The download/upload pipeline depends on multiple external systems: the file scanner (ClamAV), the policy engine, and quarantine storage. Any of these can be temporarily unavailable (crash, restart, disk full, network partition). The system must decide what happens to a file transfer when a dependency it needs for a security decision is not answering.

## Decision

Every security-relevant dependency failure results in the more restrictive outcome, never silent allow:

- Scanner unavailable → no automatic release (treated at least as QUARANTINE, never AUTO_RELEASE)
- Policy engine error → no release
- Unknown/undetectable file type → quarantine, never auto-release
- Quarantine storage unavailable → downloads are blocked entirely, not delivered around it

This rule applies uniformly across the download pipeline, upload pipeline, and policy evaluation, and is implemented in the pipeline/service layer, not left to be re-implemented ad hoc per endpoint.

## Alternatives Considered

- **Fail open with an alert** (allow the transfer, notify an admin) — rejected: an attacker who can trigger scanner unavailability (e.g. resource exhaustion) could use it to bypass scanning entirely, and it violates the project's explicit "fail closed, not fail open" principle.
- **Queue and retry indefinitely before deciding** — considered for downloads, but an indefinitely stuck decision is itself a usability failure; MVP 1 instead surfaces a clear blocked/quarantined state to the user immediately and lets an admin resolve or a background retry happen without changing the fail-closed default.

## Consequences

Users will occasionally see downloads blocked or quarantined during scanner/dependency outages that a more permissive system would have let through — an intentional trade-off. This rule must be re-verified whenever a new file-transfer code path is added (e.g. Phase 16's upload pipeline), and is one of the required integration tests in [docs/development.md](../development.md).
