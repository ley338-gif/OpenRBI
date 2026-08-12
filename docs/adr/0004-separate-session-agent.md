# ADR 0004: Separate Session Agent for privileged sandbox operations

## Status

Accepted

## Context

Creating, starting, isolating, and terminating browser sandboxes requires privileged access to the container runtime (the Docker socket, or an equivalent gVisor/Kata control surface). The web backend, however, is the most exposed component: it serves the admin/user APIs, handles user input, and is the most likely target of a web-application-level compromise. See [ADR 0005](0005-no-docker-socket-in-backend.md) and [ADR 0009's](0009-novnc-remote-display.md) related trust-boundary reasoning.

## Decision

Sandbox lifecycle operations are performed by a separate process/service, `openrbi-session-agent`, which is the only component holding the privileged runtime credentials it needs (e.g. Docker socket access) and nothing else. The control plane (backend) talks to it only through an internal, authenticated API. The interface is designed so a future deployment can run the Session Agent on a different host from the control plane (multi-node browser nodes), rather than assuming co-location.

## Alternatives Considered

- **Embed sandbox management in the backend** — simplest to build, but means a backend compromise (e.g. an API vulnerability) directly yields Docker-socket-equivalent host access. Rejected as violating the fail-closed/least-privilege principle.
- **Use a message queue instead of a direct API** — considered for decoupling, but an authenticated synchronous/async API is sufficient for MVP 1 and simpler to reason about for lifecycle operations that need timely status; queue-based orchestration can be layered in later for multi-node scheduling without changing the trust boundary.

## Consequences

Introduces one more service to deploy and secure (its own credentials, its own network exposure limited to the control plane), but it is the key control that prevents a web-app-level bug from becoming host/container-runtime compromise. It also is the natural place to later add remote browser nodes.
