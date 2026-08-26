# ADR 0023: Node enrollment and trust model (Roadmap B2.1)

## Status

Accepted

## Context

MVP 1 runs exactly one Session Agent/browser-sandbox host, implicitly
trusted: `backend/app/services/sessions.py`'s `refresh_node_from_agent()`
polls the single, operator-configured `OPENRBI_SESSION_AGENT_BASE_URL` and
auto-creates its `BrowserNode` row on first successful poll — there is no
concept of "is this a node we actually meant to add" because there has
never been more than one possible node.

[docs/roadmap-b2-multinode.md](../roadmap-b2-multinode.md)'s Phase B2.1
requires a real registry for N nodes, and explicitly flags the trust
question the single-node case never had to answer: "don't let an attacker
register a rogue node that receives real session traffic." A `BrowserNode`
row existing must not, by itself, mean the scheduler will use it.

## Decision

**Two-phase enrollment, not manual admin data entry and not automatic
trust:**

1. An admin generates a single-use **enrollment token** (`POST
   /admin/nodes/enrollment-tokens`, ADMIN-only, audited), TTL 1 hour,
   stored hashed in Redis via Redis `GETDEL` (same single-use pattern
   `app/core/release_tokens.py` already uses for quarantine release
   tokens) — never persisted in Postgres, never returned a second time.
   The admin copies it into the new host's session-agent `.env`
   (`OPENRBI_AGENT_ENROLLMENT_TOKEN`), alongside a real, freshly generated
   `OPENRBI_AGENT_API_TOKEN` the operator generates themselves exactly the
   way they already do today for the single-node case (`openssl rand -hex
   32`) — no change to how that token is produced.

2. On startup, the new Session Agent POSTs the enrollment token plus its
   own `hostname` and `api_token` to `POST /admin/nodes/enroll`
   (unauthenticated — there is no admin session on a node's own call path
   — but closed by the enrollment token itself, retried on a background
   loop with backoff if the control plane isn't reachable yet, mirroring
   `app/core/node_poller.py`'s existing retry-forever pattern rather than
   crash-looping the container). A valid, unconsumed token creates a new
   `BrowserNode` row with `enrollment_status = PENDING` and the reported
   `api_token`, encrypted at rest with the existing `app/core/crypto.py`
   `encrypt_secret()` (same key, same function already used for TOTP
   secrets — no new key material introduced for this).

3. **A `PENDING` node is never schedulable.** `select_node()` (Phase B2.3)
   will only ever consider `APPROVED` nodes — this ADR doesn't wait for
   B2.3 to land to make that true in spirit: nothing in B2.1 wires a
   `PENDING` node into scheduling or polling at all. It exists purely as a
   registry row awaiting a human decision.

4. An admin reviews pending nodes in the Admin Portal and either
   **approves** (`POST /admin/nodes/{id}/approve`, ADMIN-only, audited,
   also sets the node's `endpoint_url` — the externally-reachable address
   the control plane will later dial, which only the operator can supply
   reliably; a self-reported address is unreliable behind NAT/port
   mapping) or **revokes** (`POST /admin/nodes/{id}/revoke`, ADMIN-only,
   audited) it. `REVOKED` is terminal for that token/row — a revoked
   node's stored `api_token` is cleared, and re-enrollment requires a
   fresh enrollment token.

**Why not simpler alternatives:**

- *Manual admin data entry (admin types in hostname/endpoint/token
  directly, no agent-initiated call at all)* — rejected: forces the
  operator to correctly copy a generated token between two places by hand
  with no verification it was entered correctly on either side, and loses
  the audit trail of "this specific agent process, at this address, is
  the one that presented the token" that a live enrollment call gives for
  free.
- *Fully automatic registration (any agent presenting a valid API token
  is immediately `ONLINE` and schedulable, no approval step)* — rejected,
  per the roadmap's own explicit concern: a leaked/guessed token alone
  would be enough to receive real user session traffic on infrastructure
  the operator doesn't actually control. The two-phase model means a
  leaked enrollment token is not, by itself, sufficient — it also
  requires a second, audited, human action (`NODE_APPROVED`) before
  anything happens.
- *A single shared token for all nodes (today's model, just reused)* —
  rejected per the roadmap's blast-radius concern: compromising one
  node's token would compromise all of them. Per-node tokens (this ADR)
  cap a leak to the one node whose token leaked; revoking it doesn't
  affect any other node.

## Alternatives Considered

- **mTLS client certificates instead of a bearer enrollment token** —
  stronger, but adds a certificate-authority/issuance story this project
  doesn't have anywhere else yet (session-to-session auth today is
  uniformly bearer-token-based — CSRF, session cookies, the existing
  agent token). Deferred as a documented future hardening option, not
  required for B2.1's actual near-term audience (homelab/KMU, per the
  project's stated scope).
- **IP-allowlist-based auto-approval** (a node from a pre-configured CIDR
  range auto-approves) — rejected: reintroduces implicit trust by network
  position alone, the exact thing B2.1 exists to move away from, and
  doesn't compose with the "operator-managed overlay network, not
  automated by this repo" transport decision already made in the roadmap.

## Consequences

- A brand-new node is inert (visible, but inactive) until a human
  approves it — matches this project's fail-closed default everywhere
  else (a new user account, a new policy version, a new LDAP config all
  require an explicit activation step, never "exists therefore active").
- `BrowserNode` gains three columns (`endpoint_url`, `enrollment_status`,
  `agent_token_encrypted`) and one new enum
  (`NodeEnrollmentStatus`), plus three new `SecurityEventType` values
  (`NODE_ENROLLMENT_REQUESTED`, `NODE_APPROVED`, `NODE_REVOKED`). No
  existing column changes meaning or type.
- The existing single-node auto-creation path
  (`refresh_node_from_agent()`, driven by the operator's own trusted
  `.env` config, not network-reachable attacker input) is **unaffected**:
  `enrollment_status` defaults to `APPROVED` at the model level, so a
  Compact/single-node deployment continues to work exactly as it does
  today with zero new required steps — enrollment is additive, only
  exercised when an operator deliberately adds a second node.
- `agent_token_encrypted` is written but not yet *read* anywhere in B2.1
  — B2.2 (per-node client plumbing) is what actually starts using a
  node's own stored token instead of the single shared
  `OPENRBI_SESSION_AGENT_API_TOKEN` for outbound calls to that node. This
  ADR only establishes that the value exists, encrypted, associated with
  the right node, by the time B2.2 needs it.
