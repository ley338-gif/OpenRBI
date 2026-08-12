# ADR 0012: Compact vs. Segmented deployment profiles, one codebase

## Status

Accepted

## Context

OpenRBI's primary near-term audiences include homelab/evaluation users and small organizations running everything on one host (`README.md`'s stated scope), alongside a longer-term interest in more security-conscious/enterprise deployments that expect a real network boundary between admin and user traffic. [ADR 0011](0011-user-admin-listener-separation.md) makes that boundary possible at the process level via `OPENRBI_LISTENER_MODE`. This ADR records how that capability is meant to be *deployed*, without forcing every deployment into the more complex shape.

## Decision

Two deployment profiles, from the same codebase and the same built container image:

- **Compact** — `docker-compose.yml` unchanged, `OPENRBI_LISTENER_MODE` unset (defaults to `both`). One backend process, one reverse-proxy vhost, everything on `control-plane`. This is today's only actually-shipped profile, and remains the default and the one covered by `docs/deployment.md`'s primary instructions.
- **Segmented** — an illustrative, additive `docker-compose.segmented.yml` overlay runs two instances of the *same* backend image, `backend-user` (`OPENRBI_LISTENER_MODE=user`) and `backend-admin` (`OPENRBI_LISTENER_MODE=admin`), alongside (not replacing) the base `backend` service. This is explicitly documented as a preparatory example, not a complete production guide — it does not yet add a second reverse-proxy vhost/origin, separate database roles, or Session Agent token scoping (see [ADR 0011](0011-user-admin-listener-separation.md)'s "Alternatives Considered" for why those are deliberately deferred).

Both profiles are realistically maintainable from one codebase because [ADR 0011](0011-user-admin-listener-separation.md) already confined the entire difference between them to *how many times, and with what `OPENRBI_LISTENER_MODE`, the same built image is instantiated* — no service, model, or business-logic file differs between the profiles.

## Alternatives Considered

- **Two separate Dockerfiles/images (a "user-api" image and an "admin-api" image)** — would work but adds a build-maintenance cost (two images to version, scan, and keep in sync) for no behavioral difference over a single image parameterized by an environment variable. Rejected.
- **Kubernetes manifests / Helm chart for Segmented** — explicitly out of scope for this project's stated non-goals (`README.md`'s "Scope" section: no Kubernetes/HA/multi-node orchestration in v0.1.1). Rejected; Segmented is expressed purely as an additional Compose overlay.
- **Fully wiring Segmented now (separate vhosts, DB roles, Session Agent scopes, firewall automation)** — considered and rejected by `docs/analysis/productization-v0.1.1-zone-separation.md`'s explicit recommendation (`PREPARE FOR SEGMENTATION, IMPLEMENT LATER`): premature complexity before either a User Portal or Admin Portal exists to actually run behind these origins.

## Consequences

- Operators choosing Compact today are completely unaffected — verified via the full existing test suite passing unchanged with the default `both` mode.
- Operators wanting to experiment with the Segmented shape have a real, tested (not just described) starting point (`docker-compose.segmented.yml`, `scripts/test-listener-modes.sh`), with its current limitations explicitly documented (see the file's own comments and `docs/deployment.md`) rather than silently assumed away.
- A future, fuller Segmented production guide (separate origins/vhosts, TLS per-origin, DB role scoping, Session Agent token scoping, firewall guidance) remains a distinct, later piece of work — not implied as already done by this ADR.
