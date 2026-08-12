# Security Model

## Sandbox model

Each browser session runs in its own container (see [ADR 0010](adr/0010-docker-sandbox-provider.md)), created and destroyed exclusively by the Session Agent (see [ADR 0004](adr/0004-separate-session-agent.md)). Hardening baseline (all enforced at the container-runtime level, not just documented intent):

- non-root user inside the container
- `no-new-privileges`
- Linux capabilities dropped as fully as the browser allows
- read-only root filesystem where practical, with an explicit, size-limited tmpfs/volume for the browser profile
- no host network, no privileged mode, no Docker socket mount
- PID limit, RAM limit, CPU limit, temporary storage limit (defaults: 2 CPUs, 2 GB RAM, PID limit 512, 2 GB temp storage — all configurable, see [ADR 0010](adr/0010-docker-sandbox-provider.md) and §24 of the project brief)
- seccomp/AppArmor profiles appropriate to a browser workload
- a dedicated temporary browser-profile path, destroyed at session end (see [ADR 0007](adr/0007-no-persistent-browser-profiles.md))

## Control-plane container hardening (Phase 20)

The sandbox hardening baseline above was always container-per-session and dynamically applied by the Session Agent. Phase 20 extends the same "no component runs unnecessarily privileged" principle to the *static* `docker-compose.yml` services:

- `backend` and `session-agent` (the two custom-built, code-we-wrote services): `no-new-privileges`, all Linux capabilities dropped. `session-agent` — the one component with Docker-socket access — also runs as a non-root UID (`10001`), kept in group `0` because the bind-mounted `docker.sock` is typically `root:root`/`root:docker` with group read-write; this drops the process out of literal `uid 0` without depending on a host-specific docker-group GID. Verified end-to-end against the live Docker socket post-hardening: real sandbox create → start → status → terminate all still work as this non-root, capability-stripped user.
- `frontend` and `reverse-proxy` (both nginx): all capabilities dropped except `NET_BIND_SERVICE` (bind port 80) and `CHOWN`/`SETUID`/`SETGID`, which nginx's own startup needs to drop its *worker* processes from root to the unprivileged `nginx` user — without them, nginx either fails outright or (if its config never declares `user nginx;`, as this project's custom `reverse-proxy` config originally didn't) silently never drops privilege at all. Both are now verified (`ps aux` inside each container) to run their master process as root only for the bind, with every worker process running as `nginx`.
- `postgres`, `redis`, `clamav` (vendor images, not built by this project): `no-new-privileges` only. `cap_drop: ALL` was deliberately *not* applied to these — their own entrypoints need root-level setup capabilities (chown/setuid data directories, etc.) before dropping to their own unprivileged runtime user, and blanket-stripping capabilities at the container level risks breaking that startup sequence for images this project doesn't control. Documented as a scoped decision, not a silent gap.

## User/Admin listener separation (Productization v0.1.1)

Before this, every backend router — user-facing and admin-facing — was registered in one FastAPI process; the only boundary between them was `require_role`'s per-endpoint `403`. That's a real, effective control against one specific threat (an authenticated non-admin user trying admin endpoints) but not against another (code-execution-level compromise of the backend process itself) — a compromised process already holds the database connection, the Redis client, and the Session Agent's shared token regardless of which route the compromising request arrived through, since it's the same process either way.

`OPENRBI_LISTENER_MODE` (`app/config.py`, see [ADR 0011](adr/0011-user-admin-listener-separation.md)) makes the router set itself conditional: a `user`-mode process never imports the admin routers at all, so `/admin/*` is a `404` there — not a route that exists and gets rejected, a route that doesn't exist to call. This directly mitigates: **a compromise of a process serving only user-facing traffic can no longer reach admin *routes*** in that same process, because they were never registered.

**What this does NOT yet mitigate**, stated explicitly rather than implied:

- **Database credentials** — a `user`-mode process still connects to the same PostgreSQL with the same DB user/permissions an `admin`-mode process would use. No per-listener DB role exists yet (tracked in [ADR 0011](adr/0011-user-admin-listener-separation.md)'s "Alternatives Considered" as a later hardening option).
- **Session Agent credentials** — both listener modes, if run as separate processes, still hold the identical shared `OPENRBI_SESSION_AGENT_API_TOKEN`. A compromised `user`-mode process could still authenticate to the Session Agent and, in principle, issue any command the token permits (including isolate/terminate on sessions it has no legitimate reason to touch) — the Session Agent's own authorization has no notion of "which listener is asking." No per-listener token/scope exists yet.
- **Network segmentation** — both listener modes, when run together (`docker-compose.segmented.yml`), still sit on the same `control-plane` Docker network as everything else. No VLAN, firewall rule, or separate subnet enforces that a `user`-mode process's *network path* to Postgres/Redis/the Session Agent is any different from an `admin`-mode process's.
- **Separate origins for cookie isolation** — a User Portal and Admin Portal now exist (see below), but in the Compact deployment profile they are still served from the **same origin** (one nginx image, `/` and `/admin/`), so this benefit is not yet realized in the only shipped production profile. It becomes real only in a Segmented deployment with genuinely separate portal origins — not yet a complete production guide (see `docs/deployment.md#segmented`).

The Browser Isolation Zone this task's own analysis considered building already exists — see [Network isolation](#network-isolation) below and [ADR 0013](adr/0013-browser-isolation-zone.md); listener separation does not change it.

## Portal frontend trust placement (Productization v0.1.1)

The **Admin Portal is intended to run trusted/management-side** — reachable only from a management network in a real Segmented deployment, since it exercises every admin-only capability (user/session/policy/quarantine/incident control). The **User Portal may be DMZ-facing**, since it only ever calls the User listener's routes, which have no admin capability registered at all. **Compact mode does not yet implement this placement** — both portals and both logical listener surfaces run in the same process(es), on the same network, reachable from the same origin. Nothing in Compact should be read as "the Admin Portal is already isolated from the internet" — that separation is a Segmented-deployment property, not a Compact one, and this document explicitly avoids claiming otherwise.

Frontend-specific rules enforced by both portals: no secrets, Session Agent tokens, database credentials, or MFA secrets are ever held or logged client-side; session cookies (HttpOnly, server-side/Redis-backed) are the only credential either portal holds, with no parallel client-side token storage; every server-delivered text field is treated as untrusted for rendering (no `dangerouslySetInnerHTML` or equivalent anywhere in either app).

## Secrets — fail-closed startup validation (Phase 20)

`.env.example` always documented "services refuse to start with missing/empty secrets" as a principle, but nothing enforced it until Phase 20: `Settings` in both `backend/app/config.py` and `session-agent/app/config.py` now reject, at startup, any critical secret (`OPENRBI_SESSION_AGENT_API_TOKEN`, `OPENRBI_TOTP_SECRET_ENCRYPTION_KEY`, `OPENRBI_AGENT_API_TOKEN`) that is empty *or* still the literal placeholder value from `.env.example`. This is not a hypothetical gap: enabling the check on this project's own long-running dev deployment immediately caught `POSTGRES_PASSWORD`, `OPENRBI_SESSION_AGENT_API_TOKEN`, and `OPENRBI_AGENT_API_TOKEN` all still holding that exact unedited example value — the backend↔session-agent shared-secret check had been silently "passing" the whole time because both sides matched on a secret sitting in git. All three were rotated (the Postgres role's password changed in-place via `ALTER USER`, not by wiping the data volume) and the stack re-verified end-to-end afterward.

## Login brute-force protection (Phase 20)

`POST /auth/login` now enforces a per-username lockout (`app/core/sessions.py`: `is_login_locked`/`record_login_failure`/`clear_login_failures`, Redis-backed, 15-minute window, 10 attempts) distinct from the Phase 4 MFA-challenge attempt cap — that one only ever engages *after* a password has already been guessed correctly. Keyed by username rather than IP, since an attacker behind NAT or a botnet defeats a per-IP limit trivially, but the account being guessed at is fixed. A lockout hit returns a generic `429` (not a distinct error shape that would leak whether the username exists) and records a `LOGIN_LOCKED` security event, separate from the per-attempt `USER_LOGIN_FAILED` events, so a reviewer can see an actual lockout rather than inferring one from a burst of failures. Verified end-to-end: 10 wrong-password attempts against a real account, then an 11th attempt with the *correct* password still returns 429 until the window clears.

## Network isolation

### Topology

Two docker networks (`docker-compose.yml`, pinned subnets so firewall rules can reference them directly):

- `control-plane` (`172.28.0.0/16`) — postgres, redis, clamav, session-agent, backend, frontend, reverse-proxy.
- `browser-plane` (`172.30.0.0/24`, IPv6 disabled outright rather than replicating the IPv4 blocklist for it) — every browser sandbox container, and *only* the backend additionally, at a pinned address (`172.30.0.2`). The backend needs this for the Phase 8 display relay (a plain outbound TCP connection to a sandbox's VNC port — not a privileged operation, ADR 0005 is unaffected).

`scripts/setup-network-isolation.sh` applies the actual enforcement to the Docker host's `DOCKER-USER` iptables chain (the chain Docker itself reserves for user rules, safe from being clobbered by Docker's own chain regeneration) — run once after `docker compose up` on the deployment host. It is idempotent (a comment-tag marker lets it safely re-run after any config change) and:

- Blocks `browser-plane` from reaching the full static IPv4 list (§10): `0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 192.168.0.0/16, 198.18.0.0/15, 224.0.0.0/4, 240.0.0.0/4`.
- Blocks `browser-plane` from reaching itself (sandbox-to-sandbox / session isolation) and every *other* docker network on the host, discovered dynamically at run time — not hardcoded, so it also covers unrelated docker-compose projects sharing the same host, and Docker Desktop's own internal management subnets in dev.
- Blocks `browser-plane` from reaching the host's own IP addresses, discovered dynamically at run time (`ip -4 addr show`).
- Allows `ESTABLISHED,RELATED` return traffic for control-plane-initiated connections, and a plain `ACCEPT` for new connections specifically from the backend's pinned `172.30.0.2` — otherwise indistinguishable from a sandbox by subnet alone. Every other address in `browser-plane` (every real sandbox) still cannot open a *new* connection into the control plane; only the backend can initiate.
- Logs every blocked packet via the `LOG` target (`openrbi-blocked:` prefix) immediately ahead of its matching `DROP` rule — order matters here, since `DROP` is a terminating target and would otherwise prevent the `LOG` rule below it from ever being reached.

Verified end-to-end on the actual running stack (not just written and assumed correct): a container on `browser-plane` reaches the public internet (`HTTP 200`) but times out against Postgres's real container IP, the network gateway, `10.0.0.1`, and `169.254.169.254`; the backend still gets a real VNC banner back from a live sandbox; a sandbox cannot reach another sandbox — this last one was a one-time manual check during Phase 9 itself, since promoted to an automated regression test in `scripts/run-security-tests.sh` (Roadmap Phase A / A3, closing a gap `docs/security-self-assessment.md` found). Two real bugs were caught and fixed during this verification: the backend's own leg on `browser-plane` was being caught by the same DROP rules meant for sandboxes (fixed by pinning its address and exempting exactly that address), and the `LOG` rules were silently never firing because they were inserted *after* their matching `DROP` rule instead of before it.

### Known interim gaps (tracked, not silent)

- **No automatic `NETWORK_ACCESS_BLOCKED` security event yet.** Blocked attempts are visible via the kernel log (`dmesg`/`journalctl -k`, the `openrbi-blocked:` prefix) but nothing yet ships those lines into the application's audit log — a small log-shipper is a tracked follow-up, not built in Phase 9. (Log-line *visibility* itself was verified via packet counters incrementing correctly on this project's Windows/Docker Desktop dev environment, since Docker Desktop's virtualized kernel didn't expose `dmesg` output through `docker run --net=host`; this should be re-confirmed on the actual Linux deployment target where `dmesg` behaves normally.)
- **No dedicated DNS-rebinding-aware resolver.** The project brief allows "implement or plan" one; this blocklist already defeats DNS rebinding at the connection level regardless of how a destination address was obtained (a resolved-then-dialed blocked IP is dropped exactly like a hardcoded one), which is the required *outcome* — now backed by an automated regression test (Roadmap Phase A / A3, `scripts/run-security-tests.sh`'s DNS-rebinding check: a hostname whose DNS answer is faked via `curl --resolve` to point at Postgres's real IP is still blocked), not just this narrative claim. A dedicated resolver that rejects a malicious DNS *answer* before any connection attempt — cleaner audit signal, no wasted connect — remains planned, not built.
- **The VNC server inside each sandbox (x11vnc) runs without its own password** (`-nopw`), relying entirely on this network-level access control (only the backend's pinned address can reach it at all) rather than VNC authentication. The actual authorization boundary is the backend's session check on `/display/{id}/ws`; full per-session *ownership* enforcement there is still pending Phase 10/11's real `BrowserSession` model.

Browser sandboxes may reach the public internet only. Blocked by default, at minimum:

- IPv4: `0.0.0.0/8`, `10.0.0.0/8`, `100.64.0.0/10`, `127.0.0.0/8`, `169.254.0.0/16`, `172.16.0.0/12`, `192.0.0.0/24`, `192.168.0.0/16`, `198.18.0.0/15`, `224.0.0.0/4`, `240.0.0.0/4`
- IPv6: `::1/128`, `fc00::/7`, `fe80::/10`, `ff00::/8`
- Dynamically: Docker networks, host networks, control-plane networks, cloud metadata endpoints, management networks

DNS resolution for sandboxed sessions goes through a controlled resolver/proxy (planned, Phase 9) so that DNS answers pointing at a blocked address are rejected rather than allowed to connect — this specifically defeats DNS-rebinding attacks. Any connection attempt or resolution that would land on a blocked address is denied and generates a `NETWORK_ACCESS_BLOCKED` security event.

## File transfer

Downloads and uploads are fail-closed pipelines (see [ADR 0008](adr/0008-fail-closed.md) and [quarantine.md](quarantine.md)):

- No download reaches the local client unscanned or unvetted by policy.
- No local directory is ever mounted directly into a browser sandbox for uploads; uploads go through a dedicated gateway (hash → type detection → scan → policy → temporary in-sandbox availability).
- File decisions consider more than extension or declared Content-Type: user, groups, source, declared MIME, detected/magic-byte MIME, extension, size, scanner result, and the policy version used — recorded per-decision.

## Fail-closed rules

See [ADR 0008](adr/0008-fail-closed.md) for the authoritative statement. Summary: scanner down → no auto-release; policy engine error → no release; undetectable file type → quarantine; quarantine storage down → downloads blocked entirely. These rules apply uniformly to both the download and upload pipelines.

## MFA

TOTP is mandatory for ADMIN and SECURITY_REVIEWER roles (see [ADR 0002](adr/0002-totp-mfa.md)). TOTP secrets are encrypted at rest at the application layer. Recovery codes are shown once, stored only as hashes, and invalidated individually on use. An admin-triggered MFA reset always creates a `MFA_RESET` security event.

## Session isolation

No two users' sessions ever share a browser instance, a writable profile, or a filesystem mount. Admins/Security Reviewers can Disconnect (drop the remote-display connection, sandbox persists), Isolate (network egress deny-all, clipboard deny both directions, uploads/downloads/new file-shares deny-all, sandbox persists for investigation), or Kill (idempotent full destruction) a session — see [session-lifecycle.md](session-lifecycle.md).

## Secrets

No secrets in git. No hardcoded passwords or tokens. Database credentials, session-signing keys, and the TOTP secret-encryption key are provided via environment variables / a secrets manager at deploy time (see [deployment.md](deployment.md) and `.env.example`). The Session Agent's internal API credentials are provisioned the same way and are never accessible from inside a browser sandbox.

## Audit

Security Events are append-only and not deletable through the normal admin UI (see [docs/architecture.md](architecture.md) for the event flow, and the master event list in the project's Security Event model). Logs never contain passwords, MFA secrets, complete tokens, or file contents.

## Data protection / retention

Persisted: users, roles, groups, MFA metadata, policies and policy versions, incidents, security events, audit metadata, quarantine metadata, system configuration. Never persisted beyond session lifetime: browser cache, cookies, browser history, saved browser passwords, temporary profiles, session `/tmp` contents (see [ADR 0007](adr/0007-no-persistent-browser-profiles.md)).
