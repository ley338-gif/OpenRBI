# ADR 0006: Firefox as the first BrowserProvider

## Status

Accepted

## Context

MVP 1 needs one working remote browser end-to-end before a second is worth adding. The choice affects sandboxing options (profile isolation, process model), automation/remote-control surface, and container image size/hardening effort.

## Decision

Firefox (ESR channel) is the first `BrowserProvider` implementation, run headful inside the hardened browser container and displayed via the `DisplayProvider` (see [ADR 0009](0009-novnc-remote-display.md)). Chromium is the planned second provider once the `BrowserProvider` interface (see [ADR 0003](0003-provider-abstraction.md)) is proven against a real browser.

## Alternatives Considered

- **Chromium first** — very common in existing RBI products and has broad extension/DevTools tooling, but its multi-process model complicates resource-limit and seccomp tuning for a first hardening pass, and its release cadence is faster than ESR, meaning more frequent base-image churn.
- **Both browsers simultaneously** — spreads hardening and testing effort across two browser engines before either is proven; rejected for MVP 1.

## Consequences

MVP 1 users get only Firefox. Firefox ESR's slower, predictable release cadence simplifies keeping the browser container patched. Adding Chromium later is scoped as a new `BrowserProvider` implementation plus its own hardening/image work, not a redesign of session/display logic.
