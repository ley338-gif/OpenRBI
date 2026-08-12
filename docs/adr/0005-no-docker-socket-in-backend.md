# ADR 0005: No Docker socket access from the web backend

## Status

Accepted

## Context

Access to `/var/run/docker.sock` is equivalent to root on the host: any process that can talk to it can mount the host filesystem, escape containers, and control every other container. The web backend/API is OpenRBI's largest and most exposed codebase (REST endpoints, policy engine, user-supplied input parsing).

## Decision

The backend/API container never mounts or receives credentials for the Docker socket, in any deployment mode. All sandbox lifecycle operations go through the Session Agent (see [ADR 0004](0004-separate-session-agent.md)) over its internal authenticated API. This is enforced structurally (no volume mount, no `DOCKER_HOST` pointing at a reachable socket) not just by convention in application code.

## Alternatives Considered

- **Docker socket proxy with an ACL (e.g. a filtering proxy)** — reduces but does not eliminate risk, and still couples the backend's trust level to container-runtime operations. A fully separate, minimally-privileged service is a stronger boundary and was preferred.
- **Rely on application-level checks to restrict Docker API usage** — rejected outright: this is exactly the kind of "security decision only in application code" the project's principles forbid; a bug or injection in the backend would bypass it entirely.

## Consequences

Any change that appears to need Docker access from the backend is a signal that the operation belongs in the Session Agent's API instead. This is a hard constraint checked in code review and, longer-term, should be checked structurally (e.g. compose/deploy-time assertion that the backend container has no socket mount).
