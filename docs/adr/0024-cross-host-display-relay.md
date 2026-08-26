# ADR 0024: Cross-host display relay (Roadmap B2.4)

## Status

Accepted

## Context

`app/api/display.py`'s WebSocket handler is the live noVNC data path: it
authenticates the end user, then relays raw RFB/VNC bytes between their
browser and the sandbox's VNC port. Until this phase, it did that by
dialing the sandbox directly — `asyncio.open_connection(info.host,
info.port)` — which only works because the backend process is itself
multi-homed onto `browser-plane` (`docker-compose.yml`, static
`172.30.0.2`) alongside every sandbox container, on the *same* Docker
bridge network, on the *same* host.

[Roadmap B2](../roadmap-b2-multinode.md) breaks that assumption. Once a
`BrowserNode` genuinely lives on a different host (B2.1's enrollment,
B2.2's per-node connection, B2.3's real scheduling all already work
across hosts — only the display path doesn't), the backend has no route
to that node's private `browser-plane` bridge at all. Docker bridge
networks are host-local; nothing joins them from outside that host
without the operator building actual host-to-host L2/L3 connectivity for
container IPs specifically, which the roadmap's own "cross-host
transport" decision explicitly declines to require (an operator-managed
overlay is for reaching a node's *Session Agent API*, not for extending
its private sandbox bridge across the wire).

The same problem exists one level up: `app/services/sessions.py`'s
`_wait_for_display_ready()` also TCP-dials `info.host`/`info.port`
directly from the backend process, to confirm a newly-created sandbox's
VNC server has actually started accepting connections before reporting
the session `ACTIVE`.

## Decision

**The relay endpoint moves to the node it serves, not away.** The
client-never-reaches-a-sandbox's-VNC-port-directly invariant
(`docs/adr/0004`, `docs/adr/0005`) is preserved by relocating *where* the
relay terminates, not by removing the relay or weakening the check:

1. **Session Agent gains the relay.** A new `session-agent` route,
   `WS /v1/sandboxes/{id}/display/ws` (same
   `require_control_plane_token` auth as every other route on that
   router — the control plane's per-node token, B2.2), accepts a
   WebSocket from the control plane, resolves the sandbox's real
   `host:port` locally (it already does this today for the REST
   `GET /v1/sandboxes/{id}/display` endpoint — same provider call, same
   host), opens a plain TCP connection to it, and pumps raw bytes both
   ways. This process already lives on the sandbox's own host, on the
   same `browser-plane` bridge — the connection it opens is exactly the
   local, single-host connection the backend used to make, just executed
   from the right place.

2. **The backend now terminates a WebSocket-to-WebSocket relay, not a
   WebSocket-to-raw-TCP one.** `display_ws()` in `app/api/display.py`
   dials that per-node relay URL (derived from `NodeConnection.base_url`,
   B2.2, with `ws(s)://` substituted for `http(s)://`) using the node's
   own decrypted token, instead of opening a TCP socket. Every existing
   control this handler enforces — session ownership, `ACTIVE`/
   `DISCONNECTED`-only, Origin-vs-Host validation, real-time RFB
   clipboard-policy filtering (`app/core/rfb_clipboard_filter.py`) — is
   completely unchanged: it's still the backend, still per-request, still
   before any byte reaches the end user or the sandbox. The relay hop
   this ADR adds carries only already-filtered bytes; it does not gain
   any new authority over them.

3. **Readiness checking moves the same way.** A new REST endpoint,
   `GET /v1/sandboxes/{id}/display/ready`, does the local TCP-connect
   probe `_wait_for_display_ready()` used to do directly, and reports
   success/failure over the existing control-plane API instead. The
   backend polls this endpoint (`session_agent_client.check_display_ready()`)
   the same retry-with-backoff way it always has — only *where* the probe
   executes changed, not the race condition it exists to catch or the
   number of attempts.

4. **The backend loses its `browser-plane` membership entirely; the
   Session Agent gains it.** `docker-compose.yml` no longer multi-homes
   `backend` onto `browser-plane` — it has no remaining reason to reach
   that network at all once (1)–(3) land. `session-agent` is attached
   instead, at the address the old exemption used
   (`172.30.0.2`, now meaning the agent). This is a net narrowing of the
   control plane's own network footprint, not just a like-for-like move:
   the one component this project already treats as holding
   runtime-level privilege (`docs/adr/0004`) is the one that gains a
   second network, and the one that previously had the narrowest
   privilege model (the backend, `docs/adr/0005`) gets strictly less
   reach than before.

5. **Per-node subnets.** `browser-plane`'s CIDR becomes a documented
   per-deployment override (`OPENRBI_BROWSER_PLANE_SUBNET`, default
   unchanged `172.30.0.0/24`) rather than a value hardcoded in
   `docker-compose.yml` — the minimum needed so a second host's own
   compose file (Roadmap B2.6) can pick a distinct, non-colliding range
   (e.g. `172.30.<node-index>.0/24`) for its own local `browser-plane`.
   Each node's `browser-plane` remains host-local; there is still no
   single flat sandbox network spanning multiple hosts.

6. **`scripts/setup-network-isolation.sh`'s exemption follows the relay.**
   The address allowed to open *new* connections into `browser-plane`
   (previously `OPENRBI_BACKEND_BROWSER_PLANE_IP`, defaulting to the
   backend's `172.30.0.2`) is renamed `OPENRBI_AGENT_BROWSER_PLANE_IP`
   and now defaults to the Session Agent's address at the same numeric
   default — a deliberate breaking rename (this project has already had
   a GA release, so silently repointing an existing variable's meaning
   to a different, now-removed container without renaming it would be
   the actively dangerous choice: an operator's existing override would
   silently stop applying to anything, breaking their display relay on
   upgrade with no error). `docker-compose.segmented.yml`'s `backend-user`
   loses its `browser-plane` membership and static IP for the same
   reason `backend` does above — it was only ever there because it used
   to own `display_ws()`'s outbound connection.

## Alternatives Considered

- **Extend `browser-plane` across hosts with an overlay network
  (WireGuard/VXLAN), keep the backend dialing sandboxes directly** —
  rejected. This is exactly the shape the roadmap's own "cross-host
  transport" decision already ruled out: it would make sandbox container
  IPs themselves reachable from the control-plane host, a far larger
  network-exposure surface than exposing one relay endpoint per node, and
  would require this project to manage cross-host container networking
  itself rather than treating that as the documented operator boundary it
  already is for the Session Agent API.
- **A generic reverse TCP tunnel/port-forward from the node back to the
  control plane, instead of an application-level relay endpoint** —
  rejected: reuses none of the existing per-node authentication
  (`NodeConnection`/`connection_for_node()`, B2.2) or request/response
  shape the rest of this API already has, and a raw tunnel has no natural
  place to enforce "only this session's owner, only while ACTIVE/
  DISCONNECTED" — that check would either move to the tunnel layer
  (duplicating `display_ws()`'s own logic in a second place) or be lost
  entirely.
- **Keep the readiness TCP probe on the backend, only move the actual
  relay** — rejected: the probe has the identical cross-host reachability
  problem the relay does (same host-local `browser-plane` bridge), and
  leaving it unfixed would mean `create_session()` reports sessions on
  remote nodes `ACTIVE` without ever having actually confirmed their
  display is reachable — silently reintroducing the exact race
  `_wait_for_display_ready()` exists to catch (see its own docstring),
  just for every non-default node.

## Consequences

- `docs/architecture.md`'s trust-boundary description of the display path
  is updated: the backend no longer holds a `browser-plane` address at
  all; the Session Agent does, in addition to its existing Docker-socket
  privilege.
- `session-agent`'s own attack surface grows by one authenticated
  WebSocket route and one authenticated REST route, both gated by the
  same per-node token every other route on that service already
  requires — no new trust boundary is introduced, the existing one
  (control plane ↔ this specific node) now also covers display traffic.
- `OPENRBI_BACKEND_BROWSER_PLANE_IP` is removed;
  `OPENRBI_AGENT_BROWSER_PLANE_IP` replaces it. Documented as a breaking
  change (`CHANGELOG.md`) — an operator with a systemd timer or cron job
  calling `setup-network-isolation.sh` with the old variable name needs
  to update it on upgrade, or the script simply falls back to its new
  default (correct for the common case: an un-overridden single-node
  Compact deployment needs no operator action at all, since the default
  numeric address is unchanged).
- **Verification gap, stated plainly:** this phase's own Definition of
  Done calls for proving the relay round-trips through a genuinely
  separate second host, not two containers on one Docker host pretending
  to be separate hosts. That two-host verification has **not** been
  performed as part of landing this ADR — everything here is verified
  against the existing single-host `docker-compose` stack (a second,
  independently-addressed Session Agent container standing in for a
  second node, same technique every earlier B2 phase's tests already
  use). The architecture is designed specifically to not depend on
  same-host assumptions (no code path here checks or assumes IP
  adjacency), but that is a design claim until it's exercised against
  real separate hardware. Tracked as an open item for Roadmap B2.6/B2.7,
  which are where a real second-host deployment is first exercised at
  all.
