# Architecture Decision Records

Each ADR records one decision, its context and the alternatives that were rejected. ADRs are not rewritten when later work changes the picture; instead the **Status** section of the affected ADR gets a short note pointing to what changed. New ADRs start from [template.md](template.md) and take the next free number.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-local-auth-mvp.md) | Local username/password authentication for MVP 1 | Accepted |
| [0002](0002-totp-mfa.md) | TOTP for multi-factor authentication | Accepted |
| [0003](0003-provider-abstraction.md) | Provider abstraction for sandbox, display, browser, and scanner | Accepted — only the sandbox seam is implemented |
| [0004](0004-separate-session-agent.md) | Separate Session Agent for privileged sandbox operations | Accepted |
| [0005](0005-no-docker-socket-in-backend.md) | No Docker socket access from the web backend | Accepted |
| [0006](0006-firefox-first-browser.md) | Firefox as the first BrowserProvider | Accepted |
| [0007](0007-no-persistent-browser-profiles.md) | No persistent browser profiles in MVP 1 | Accepted |
| [0008](0008-fail-closed.md) | Fail closed on every security-relevant dependency failure | Accepted |
| [0009](0009-novnc-remote-display.md) | noVNC as the first DisplayProvider | Accepted |
| [0010](0010-docker-sandbox-provider.md) | Docker as the first SandboxProvider, gVisor as an optional additional runtime | Accepted — gVisor provider not built |
| [0011](0011-user-admin-listener-separation.md) | User/Admin API surface separation via listener mode, not a service split | Accepted |
| [0012](0012-compact-vs-segmented-deployment.md) | Compact vs. Segmented deployment profiles, one codebase | Accepted |
| [0013](0013-browser-isolation-zone.md) | The Browser Isolation Zone already exists (`browser-plane`) — no new zone | Accepted, amended by 0024 |
| [0014](0014-separate-user-and-admin-portal-frontends.md) | Separate User Portal and Admin Portal frontends, one shared codebase | Accepted |
| [0015](0015-auth-provider-abstraction.md) | AuthProvider abstraction for local + LDAP authentication | Accepted |
| [0016](0016-ldap-admin-configuration.md) | Admin-portal-managed LDAP configuration | Accepted |
| [0017](0017-first-run-bootstrap.md) | First-run bootstrap of the initial local administrator | Accepted |
| [0018](0018-worker-telemetry-and-health.md) | Worker telemetry and a centrally-defined health model | Accepted, amended by Roadmap B2/B3 |
| [0019](0019-metrics-history-and-operations-dashboard.md) | Metrics history and the Operations Dashboard | Accepted |
| [0020](0020-redis-to-valkey.md) | Redis → Valkey | Accepted |
| [0021](0021-orphan-container-reconciliation.md) | Orphan-container reconciliation | Accepted, amended by Roadmap B2.5 |
| [0022](0022-quarantine-retention.md) | Downloads/quarantine retention | Accepted |
| [0023](0023-node-enrollment-and-trust-model.md) | Node enrollment and trust model (Roadmap B2.1) | Accepted, see status note |
| [0024](0024-cross-host-display-relay.md) | Cross-host display relay (Roadmap B2.4) | Accepted, see status note |
| [0025](0025-segmented-credential-scoping.md) | Per-listener Postgres roles and Session Agent token scopes for Segmented deployment | Accepted, see status note |
| [0026](0026-clipboard-policy-relay-enforcement.md) | Clipboard policy enforcement at the RFB relay, not full protocol parsing | Accepted (formerly numbered 0022) |
