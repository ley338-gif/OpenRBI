# Supported configurations

This is the authoritative OpenRBI 1.0 support matrix. It describes the deliberately small production path the v1 release is qualified against; it is not a promise that every compatible-looking combination works.

OpenRBI has completed the v1 acceptance suite introduced by V1-008 and reached a stable v1.0.x release. A configuration outside this matrix (any host/runtime/topology not listed as supported below) is not release-qualified and should not be treated as production-ready.

## Supported for OpenRBI 1.0

| Area | Supported configuration | Boundary |
|---|---|---|
| Host | A maintained x86_64 Linux host | A real Linux networking stack with `iptables`, `ip`, and the Docker `DOCKER-USER` chain is required. Windows, macOS, and Docker Desktop are development-only. |
| Container runtime | Rootful Docker Engine 27 or newer | The Session Agent uses the Docker API/socket and the isolation script programs host firewall rules. Rootless Docker is not release-qualified. |
| Compose | Docker Compose plugin v2.24 or newer | The supported deployment is the repository's Compact `docker-compose.yml` plus the production TLS overlay. Legacy `docker-compose` v1 is not supported. |
| Deployment topology | Compact, single host | One control plane and one Docker browser worker on the same host. This is the only v1 production topology. |
| Database | PostgreSQL 16.x | The shipped image is `postgres:16-alpine`. Other PostgreSQL majors are not part of v1 qualification. |
| Transient state | Valkey 8.x | The shipped image is `valkey/valkey:8-alpine`, addressed by the historical internal hostname `redis`. A Redis server is protocol-compatible in many cases but is not release-qualified for v1. |
| Malware scanner | ClamAV 1.5.4 | The Compact deployment pins `clamav/clamav:1.5.4`. Scanner failure must remain fail-closed. |
| Browser sandbox | The OpenRBI Firefox ESR image | Built from the release's `docker/browser/Dockerfile` by `scripts/deploy.sh` (`scripts/build-browser-image.sh`), which installs Debian Bookworm's current Firefox ESR security release, or the release-published `openrbi-browser` image pinned by digest. Other Firefox packages or browser images are not supported. |
| Authentication | Local accounts and LDAP/LDAPS | Plain `ldap://` without StartTLS is rejected. LDAP outage and invalid credentials must not fall back to unauthorized local access. |
| MFA | TOTP plus recovery codes | Privileged roles require TOTP enrollment. Admin MFA reset is supported and audited. WebAuthn is not part of v1. |
| Edge | Shipped nginx reverse proxy with TLS | A valid operator-provided certificate, HTTPS, `OPENRBI_ENVIRONMENT=production`, and the documented host firewall are required for network-reachable deployments. |

The version ranges above define compatibility policy. Release artifacts additionally record exact image digests, CycloneDX SBOMs and build metadata (`release-metadata.json`, see [release/publishing.md](release/publishing.md)) so a published release can be reproduced and audited.

## Experimental / technology preview

These configurations may be useful for evaluation, but they are not production-supported in v1 and are not release blockers:

- **Segmented Deployment** (`docker-compose.segmented.yml`). Listener separation works, and per-listener database roles and scoped Session Agent tokens are available opt-in ([ADR 0025](adr/0025-segmented-credential-scoping.md)). Separate reverse-proxy origins and complete network segmentation are still incomplete.
- **Multi-node** (`docker-compose.node.yml`, see [deployment.md](deployment.md)). Node enrollment, scheduling across nodes, the cross-host display relay and node-down handling are implemented and tested in CI. Not production-supported: no HA, no live session migration, and the cross-host display relay has not yet been verified on two real hosts ([ADR 0024](adr/0024-cross-host-display-relay.md)).
- **gVisor/runsc**. The architecture discusses it as a stronger optional runtime, but the current release path does not install, configure, or continuously test it. Treat it as an operator experiment, not an OpenRBI-supported security boundary.

## Not supported in OpenRBI 1.0

- Kubernetes, Helm, High Availability, multi-region, or automated failover
- multi-node as a production path (see the technology preview above)
- SAML, OIDC, or WebAuthn authentication
- Chromium, Chrome, Edge, Safari, or multiple selectable browser engines
- persistent browser profiles, cookies, or history
- Docker Desktop, Windows hosts, macOS hosts, or rootless Docker for production
- Redis server as a release-qualified replacement for the shipped Valkey service
- full DLP/CDR, SSL inspection, enterprise SIEM integrations, or a public API

## Qualification rule

A configuration is supported only when all of the following are true:

1. It appears in the supported table above.
2. The release commit passed the required [release gates](release/release-gates.md).
3. The exact release completed the applicable v1 acceptance scenarios on that configuration.
4. The deployment follows [deployment.md](deployment.md), including TLS, firewall, secret generation, migrations, and browser-image/network-isolation setup.

If implementation, tests, and documentation disagree, use implementation first, then tests, and treat the documentation discrepancy as a release defect.
