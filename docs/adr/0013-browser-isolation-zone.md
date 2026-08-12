# ADR 0013: The Browser Isolation Zone already exists (`browser-plane`) — no new zone

## Status

Accepted

## Context

Productization v0.1.1 planning (`docs/analysis/productization-v0.1.1-zone-separation.md`) evaluated a proposed three-zone architecture — DMZ (user-facing), Trusted (admin/control), and a distinct Browser Isolation Zone for sandbox nodes — as a hypothesis, not an assumption. The analysis found that the third zone's actual purpose (deny a compromised browser sandbox any path to the control plane, the host, other sandboxes, or the outside world beyond plain internet egress) is already fully implemented: `browser-plane` (`docker-compose.yml`, a dedicated, pinned-subnet Docker network with IPv6 disabled outright) plus `scripts/setup-network-isolation.sh`'s `DOCKER-USER` iptables rules, which block RFC1918/link-local/loopback/every other Docker network/the host's own IPs, and were verified live (not just asserted) during Phase 9 and again during the DoD walkthrough (a real sandbox reaching the public internet but not Postgres's real IP or the cloud-metadata address). This existed before this ADR and before the Productization v0.1.1 work; this ADR's purpose is purely to give it the explicit architectural-decision record it never had (previously documented only via inline `docker-compose.yml` comments and prose in `docs/security-model.md`).

## Decision

No new Browser Isolation Zone is built. `browser-plane` is retroactively recognized, in this ADR, as already satisfying the role that zone would play: browser sandbox containers are network-isolated from `control-plane` (where Postgres, Redis, the Session Agent, and the backend's own database/credentials live), from each other, from the host, and from every other Docker network, with only the backend's single pinned address permitted to *initiate* a connection into `browser-plane` (for the noVNC display relay) and only `ESTABLISHED`/`RELATED` return traffic otherwise. Productization v0.1.1's listener-mode work ([ADR 0011](0011-user-admin-listener-separation.md)) does not touch this boundary at all — a `user`-mode backend instance would need the exact same pinned-address exemption as the base `backend` service to run the display relay itself (see `docker-compose.segmented.yml`'s documented, not-yet-fixed limitation), but that is an extension of the existing model, not a new one.

## Alternatives Considered

- **A physically separate host/network segment for browser nodes** — the multi-node-readiness groundwork (`BrowserNode` as a first-class entity, `select_node()`'s abstract scheduling seam) already anticipates this for a future *multi-host* deployment, but nothing in the current single-host Compact or illustrative Segmented profile requires it now, and building it prematurely would be exactly the kind of complexity `docs/analysis/productization-v0.1.1-zone-separation.md` explicitly warned against introducing without a concrete need.
- **Renaming/restructuring `browser-plane` to match this task's three-zone vocabulary more literally** — considered and rejected as unnecessary churn: the existing name and documentation already describe the same boundary correctly; this ADR closes the gap by giving it a decision record, not by renaming working infrastructure.

## Consequences

- `docs/architecture.md` and `docs/security-model.md` continue to describe `browser-plane` under its existing name; this ADR is the cross-reference a reader following "Browser Isolation Zone" terminology from the Productization analysis should land on.
- No code, network, or iptables change accompanies this ADR — it is a documentation-only decision record for infrastructure that already exists and was already verified.
