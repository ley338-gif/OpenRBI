# Deployment

This guide's production procedure applies only to the Compact, single-host Linux path in the authoritative [supported configuration matrix](supported-configurations.md). The Segmented overlay later in this document is **experimental / technology preview**, not a supported OpenRBI 1.0 production deployment.

## Requirements

- A Linux server with Docker Engine and the Docker Compose plugin. The network-isolation script (`scripts/setup-network-isolation.sh`) requires real Linux `iptables`/`ip`/root — it is not meaningfully testable through Docker Desktop's own VM indirection, so a genuine Linux host is required for a real deployment, not just for local development.
- A domain name pointed at the server, and a TLS certificate for it (see [TLS](#tls) below), for any deployment reachable over the network. Skip this only for a fully local/offline evaluation.
- Enough disk for the Postgres volume, the quarantine-staging volume, and the browser sandbox image (`docker/browser/`, built separately — see below).

## Installation

```bash
git clone <this-repo>
cd OpenRBI

cp .env.example .env
# Edit .env: every secret must be a real generated value. This is enforced
# in code, not just convention — backend/app/config.py and
# session-agent/app/config.py refuse to start if a critical secret (the
# backend<->session-agent shared token, the TOTP encryption key) is empty
# or still the literal placeholder text (see docs/security-model.md
# #secrets-fail-closed-startup-validation-phase-20). Generate each with:
#   openssl rand -hex 32

# REQUIRED, host-specific — found by actually running the upgrade
# acceptance test on real infrastructure, not by CI (whose runners paper
# over this with their own chmod 666 workaround): session-agent runs
# as a non-root user and cannot reach /var/run/docker.sock at all without
# this. docker-compose.yml refuses to start session-agent without it set.
echo "OPENRBI_DOCKER_SOCKET_GID=$(stat -c '%g' /var/run/docker.sock)" >> .env

docker compose up -d --build

# Building this way reports version=1.0.0/commit_sha=unknown for every
# image (each Dockerfile's ARG defaults, RBI-POST-014) — fine for a quick
# local check, but useless for "which exact code is this" later. Use
# scripts/build.sh instead of `docker compose build`/`up --build` for a
# build that reports its real git version/commit/date:
#   ./scripts/build.sh && docker compose up -d
# See "Local build version metadata" below.

# The browser sandbox image isn't a compose service — the Session Agent
# spawns per-session containers from it directly. Build it once (and
# whenever docker/browser/ changes):
./scripts/build-browser-image.sh

# Apply the browser-plane network egress blocklist (docs/security-model.md
# #network-isolation) — requires root, and must be re-run after any change
# to which docker networks exist on the host:
sudo ./scripts/setup-network-isolation.sh
```

At this point the stack is reachable on `http://<host>:8080` — the **User Portal** at `/` and the **Admin Portal** at `/admin/` — fine for local evaluation, **not** for any real deployment (no TLS, session cookies never get `Secure`, port 8080 rather than 443). Continue below for an actual deployment.

## Network isolation

**`docker compose up` alone is NOT enough for production.** It brings up the browser sandboxes' network, but nothing about `docker compose up` itself applies the egress blocklist (RFC1918/link-local/metadata/inter-sandbox/host-IP, `scripts/setup-network-isolation.sh`) that actually isolates a compromised sandbox from everything it must not reach. Running that script once (RBI-POST-002), on the real host, as root, is a required and separate step for any real deployment — it cannot be done from inside a container, deliberately: the backend has no host/root access (same minimal-privilege boundary as [ADR 0005](adr/0005-no-docker-socket-in-backend.md)), so it cannot apply or self-verify these rules on its own.

**The Admin dashboard's health status now surfaces this** (`network_isolation` component, `/admin` health endpoint): the script writes a marker file (`/var/lib/openrbi/network-isolation/marker` on the host, bind-mounted read-only into the backend container) each time it successfully applies the rules, and the backend reports:

- **`NOT_CONFIGURED`** — the marker file doesn't exist. Either the script has never been run on this host, or `OPENRBI_NETWORK_ISOLATION_MARKER_DIR`/the bind mount don't line up. Shown to admins as: *"Browser network isolation is not verified. Do not use OpenRBI in production until the isolation rules are applied."*
- **`DEGRADED`** — a marker exists but is older than the freshness window (`OPENRBI_NETWORK_ISOLATION_MAX_STALENESS_SECONDS`, default 900s) — the rules were applied at some point but haven't been reconfirmed recently enough to trust, most commonly because the host rebooted (which does **not** re-run the script by itself) and no timer unit is installed.
- **`HEALTHY`** — a valid, recent marker exists.

This is a presence/freshness check on a self-attested marker file, not a live re-read of the kernel's iptables tables — the backend container is deliberately not granted the host privilege that would take. It reliably catches "nobody ever ran the script" and "the script hasn't been reconfirmed in a long time" (the two most common real-world gaps: initial setup skipped, or a host reboot / Docker restart / network recreation silently un-applying the rules), but it cannot detect someone manually flushing `DOCKER-USER` out from under a fresh marker between runs.

**Re-running after restarts** — install the provided systemd timer so this happens automatically instead of depending on someone remembering:

```
sudo cp scripts/systemd/openrbi-network-isolation.service /etc/systemd/system/
sudo cp scripts/systemd/openrbi-network-isolation.timer /etc/systemd/system/
# edit WorkingDirectory in the .service file to match where this repo is checked out
sudo systemctl daemon-reload
sudo systemctl enable --now openrbi-network-isolation.timer
```

Without this timer (or an equivalent host-level automation you set up yourself), re-run `sudo ./scripts/setup-network-isolation.sh` manually after every: host reboot, Docker daemon restart, `docker compose down && up` that recreates the `browser-plane` network, and any change to `OPENRBI_BROWSER_PLANE_NETWORK`/`OPENRBI_AGENT_BROWSER_PLANE_IP`. `./scripts/setup-network-isolation.sh --remove` clears both the iptables rules and the marker file (health immediately reports `NOT_CONFIGURED`, never a stale `HEALTHY`).

## Local build version metadata (RBI-POST-014)

**Official release build** — `.github/workflows/release.yml` sets `OPENRBI_VERSION` (the actual release tag), `OPENRBI_COMMIT_SHA` (`$GITHUB_SHA`), and `OPENRBI_BUILD_DATE` (a real UTC timestamp) as build args for every image; `docker inspect`, `/health`, and `/admin/health` all report the real values for an image pulled from `ghcr.io`.

**Local/development build** — a plain `docker compose build` (or `up --build`) passes none of these, so every locally-built image silently falls back to each Dockerfile's `ARG` defaults: `OPENRBI_VERSION=1.0.0` (hardcoded, never changes), `OPENRBI_COMMIT_SHA=unknown`, `OPENRBI_BUILD_DATE=unknown` — the same "1.0.0/unknown" regardless of what's actually checked out, which is close to useless for "which exact code is running" during local debugging or support. Use `scripts/build.sh` instead:

```bash
./scripts/build.sh          # build every service
./scripts/build.sh backend  # or just one, same as `docker compose build backend`
docker compose up -d
```

It computes real values from the current checkout (`git describe --tags --always --dirty` for version, `git rev-parse HEAD` for commit, the actual UTC time for build date) and passes them as `--build-arg`s — no `.git`-context Dockerfile magic, just explicit values computed on the host before the build starts, so it works the same way regardless of Docker's build context handling. Falls back to `docker compose build` unchanged (Dockerfile defaults) if run outside a git checkout at all.

## First-run setup (Roadmap B1.9)

A fresh installation has no user accounts at all yet — there is no default `admin`/`admin` or any other built-in credential, and **no manual database access or SQL is ever required** to create the first one. Open the Admin Portal (`/admin/`); since no administrator exists yet, it shows **Initial System Setup** instead of the normal login form.

Retrieve the one-time setup token from the backend container's own console output:

```bash
docker compose logs backend | grep -A3 "initial setup token"
```

Enter that token together with a username and password for the first administrator within 30 minutes (configurable with `OPENRBI_SETUP_TOKEN_TTL_SECONDS`), then complete the mandatory TOTP enrollment exactly like any other first-time `ADMIN` login (QR code, confirm, save the one-time recovery codes). Once that finishes, the installation is **permanently initialized** — the setup token and setup endpoints stop working immediately, and deleting every user later does not reopen them (see [ADR 0017](adr/0017-first-run-bootstrap.md) for why `COUNT(users) == 0` was deliberately rejected as the check). If the token is lost or expires before setup completes, restart the backend (`docker compose restart backend`) — a fresh token is generated and logged on every startup for as long as the system remains uninitialized.

**Keep at least one local `ADMIN` account with a real password at all times** — see `docs/admin-guide.md`'s break-glass note. There is currently no separate account-recovery process if every local administrator is lost.

## TLS

`docker-compose.prod.yml` is an overlay that switches the reverse proxy to `docker/nginx/nginx.tls.conf`: TLS termination on 443, HSTS, and a 301 redirect from plain 80. It expects a certificate at `./certs/fullchain.pem` and `./certs/privkey.pem` on the host (standard certbot/Let's Encrypt output layout — a certbot renewal hook can drop renewed files straight into `./certs/` with no config change here). nginx refuses to start without them, which is the correct fail-closed behavior for a reverse proxy whose entire job is terminating TLS.

```bash
mkdir -p certs
# Obtain a real certificate however your organization normally does
# (certbot, an internal CA, a purchased cert) and place it at:
#   certs/fullchain.pem
#   certs/privkey.pem

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Set `OPENRBI_ENVIRONMENT=production` in `.env` once TLS is in place — this flips the session cookie to `Secure` (HTTPS-only), so it should not be set before a real certificate is actually serving traffic (see [ADR 0008](adr/0008-fail-closed.md)).

`docker-compose.prod.yml` adds `80:80` and `443:443` alongside the base file's `8080:80` — the extra `8080` binding is harmless on the Docker host itself; see [Firewall](#firewall) below for what to actually expose.

## Firewall

Only expose what needs to be internet-reachable:

- **443** (HTTPS) — required.
- **80** (HTTP) — optional, only needed for the redirect to 443 and/or certbot's HTTP-01 challenge.
- Everything else (5432/Postgres, 6379/Redis, 3310/ClamAV, 8100/Session Agent, the Docker socket, the compose file's own `8080` dev binding) must **not** be reachable from outside the host — they're only ever meant to be reached container-to-container on `control-plane`, which `docker-compose.yml` already keeps off the host network. A host-level firewall (e.g. `ufw`, cloud security groups) should still explicitly deny all of these as a second layer, since a compose misconfiguration or a future added `ports:` entry should not be the only thing standing between them and the internet.

## Storage layout

Two named Docker volumes hold everything persistent (`docker-compose.yml`):

- `postgres-data` — the database: users, roles, groups, policies and policy versions, sessions, incidents, security events, quarantine metadata.
- `quarantine-staging` — the actual bytes of every intercepted download/upload, content-addressed by SHA-256, until released/rejected/deleted (see [quarantine.md](quarantine.md)).

Nothing about a browser session itself is persisted — no profile, cookies, history, or cache outlives the session (see [ADR 0007](adr/0007-no-persistent-browser-profiles.md)); there is no volume for it because there is deliberately nothing to store.

## Secret rotation

Roadmap Phase A / A6. Every secret in `.env` can be rotated, but they are not all equally simple — one of them (`OPENRBI_TOTP_SECRET_ENCRYPTION_KEY`) encrypts data already at rest, and rotating it wrong locks every enrolled user out of MFA with no self-service recovery. Generate every new value with `openssl rand -hex 32`.

**`POSTGRES_PASSWORD` / `OPENRBI_DATABASE_URL`** — change the role's actual password first, then the config, then restart:
```bash
docker compose exec postgres psql -U openrbi -c "ALTER USER openrbi WITH PASSWORD '<new-password>';"
# Edit .env: POSTGRES_PASSWORD and the password embedded in OPENRBI_DATABASE_URL must both change to the same new value.
docker compose up -d backend session-agent
```
This is the same in-place procedure ([docs/security-model.md](security-model.md#control-plane-container-hardening-phase-20)) used the one time this project's own dev deployment needed it — never wipe the data volume to "rotate" a password.

**`OPENRBI_SESSION_AGENT_API_TOKEN` / `OPENRBI_AGENT_API_TOKEN`** — these two names hold the *same* shared secret (backend sends it, session-agent validates against it; see `docs/security-model.md`'s account of the real bug caused by them silently matching on the placeholder instead of a real value). Generate one new value, set both in `.env`, then restart both services together:
```bash
docker compose up -d backend session-agent
```
There is a brief window between the two containers restarting where they disagree — session lifecycle calls will fail with a clear auth error during it, not silently. Acceptable for a planned rotation; not zero-downtime.

**`OPENRBI_TOTP_SECRET_ENCRYPTION_KEY`** — encrypts every enrolled user's TOTP secret at rest (`users.totp_secret_encrypted`, Fernet, `app/core/crypto.py`). Editing `.env` and restarting **without re-encrypting first** makes every existing secret permanently undecryptable — every enrolled admin/security-reviewer/user is locked out of MFA on their next login, with no self-service recovery (recovery codes are hashed and single-use, unrelated to this key). Use `scripts/rotate-totp-key.sh` instead:
```bash
./scripts/rotate-totp-key.sh <old-key> <new-key>            # dry run first — prints what would change
./scripts/rotate-totp-key.sh <old-key> <new-key> --apply    # commits the re-encryption
# Only then: update OPENRBI_TOTP_SECRET_ENCRYPTION_KEY=<new-key> in .env
docker compose up -d backend
```
Verified end-to-end against the live stack: enrolled a real TOTP secret, ran the rotation, restarted `backend` with the new key configured, and confirmed the app's own `decrypt_secret()` still recovered the original plaintext under the new key. Do the `.env` update and restart promptly after `--apply` succeeds — until then, the DB holds secrets encrypted under the new key while `backend` is still configured with the old one, and MFA verification fails for everyone in that window.

**`OPENRBI_CSRF_SECRET_KEY`** (RBI-POST-003, [docs/security-model.md](security-model.md#csrf-protection-rbi-post-003)) — signs the CSRF double-submit cookie only; nothing is encrypted at rest under it, so rotation is simple:
```bash
# Edit .env: OPENRBI_CSRF_SECRET_KEY=<new-key>
docker compose up -d backend
```
Every `csrf_token` cookie issued under the old key stops validating immediately on restart. Any browser tab with an open session gets one CSRF-rejected request (403) on its next mutating action; a page reload (a plain `GET`, which the CSRF check never blocks) picks up a fresh cookie from the new key and subsequent actions succeed normally — no session/login impact, no re-authentication needed.

## Backup and restore

```bash
./scripts/backup.sh [output-directory]     # default: ./backups
```

Produces a gzip'd `pg_dump` (built with `--clean --if-exists`, so restoring it is idempotent against a database that already has the same or an older schema) and a gzip'd tarball of the `quarantine-staging` volume, both timestamped.

**This backup does NOT include `.env` or TLS certificates/keys (RBI-POST-005).** Specifically, `./scripts/backup.sh` backs up exactly two things:

- PostgreSQL (`postgres-data`)
- Quarantine (`quarantine-staging`)

It does **not** back up:

- `.env` — every secret in it, most critically **`OPENRBI_TOTP_SECRET_ENCRYPTION_KEY`**
- TLS private keys/certificates (`./certs/`)
- Anything held in an external secret store, if you use one instead of `.env`

**Without the original `OPENRBI_TOTP_SECRET_ENCRYPTION_KEY`, the TOTP secrets restored from a database backup cannot be decrypted** — every enrolled ADMIN/SECURITY_REVIEWER/USER account is locked out of MFA on its next login, with no self-service recovery (recovery codes are hashed and single-use, and are themselves useless without a working TOTP-protected account to redeem them against in the first place, per [ADR 0002](adr/0002-totp-mfa.md)). This is the exact same failure mode described under [Secret rotation](#secret-rotation) above for a *botched rotation* — restoring the database without also restoring the matching `.env` has the identical effect, because the encrypted secrets in the DB backup are only ever meaningful together with the key that encrypted them.

Recommended: back up `.env` and `./certs/` separately, encrypted at rest, on a schedule tied to when they actually change (secret rotation, cert renewal) rather than the routine DB/quarantine backup cadence — e.g. `gpg`-encrypt a tarball of both and store it wherever your organization already keeps secrets/credentials, never alongside the routine backup tarball unencrypted. Do not fold `.env`/certs into `backup.sh`'s own tarball without deliberately accepting the consequence: that tarball would then itself need the same at-rest protection as `.env` currently gets (mode `600`, restricted access) — a plain `db+quarantine` backup has no such requirement today because it contains no directly usable credentials on its own.

```bash
./scripts/restore.sh <db-dump.sql.gz> <quarantine.tar.gz>
```

`restore.sh` restores the database and quarantine storage only, exactly matching what `backup.sh` produced — restoring onto a host whose `.env` doesn't match the `OPENRBI_TOTP_SECRET_ENCRYPTION_KEY` that was active when the backup was taken reproduces the MFA-lockout scenario above. Restoring `.env`/certs (from wherever you separately backed them up) is a manual step outside this script's scope, and must happen *before* restarting `backend` with the restored database if you want existing MFA enrollments to keep working.

**Destructive** — overwrites the live database and quarantine storage. Asks for an explicit `yes` before doing anything. Stops `backend`/`session-agent` for the database restore (nothing should be querying mid-restore) and restarts them afterward. If the backup predates the current schema, run the [update procedure](#update-procedure)'s `alembic upgrade head` step afterward.

`restore.sh` validates both compressed artifacts before requesting confirmation,
stops application writers while replacing the data, restarts stopped services
even if recovery fails, and restarts `reverse-proxy` after a successful restore
to clear nginx's cached upstream addresses.

### Automated restore test protocol

Before an RC, run the current-schema recovery gate from a clean clone:

```bash
./scripts/run-backup-restore-acceptance.sh
```

It records all application-table counts, backs up realistic users, policies,
security events and quarantine data, deliberately corrupts both database and
file state, restores them, compares exact records and bytes, then proves login,
a real browser session, health, reverse proxy and both portals still work. See
[Backup and restore acceptance](release/backup-restore-acceptance.md) for the
full evidence contract.

### Upgrade and rollback

The supported Compact operator sequence is defined in the
[upgrade runbook](release/upgrade.md), with recovery in the
[rollback runbook](release/rollback.md). Its executable 0.1.1-to-v1 gate and
known qualification limitations are recorded in
[Upgrade acceptance](release/upgrade-acceptance.md). Always take and validate a
database/quarantine backup, preserve the existing `.env` encryption keys, run
Alembic from the target backend image, and verify authentication, downloads,
sandbox lifecycle, health and proxy behavior before reopening access.

### Clean-install release acceptance

Before an RC, run the automated 16-step clean-host protocol from a fresh clone:

```bash
./scripts/run-fresh-install-acceptance.sh
```

It is destructive only to its dedicated `openrbi-acceptance` Compose project
and refuses to overwrite an existing `.env`. Requirements, exact assertions,
and cleanup behavior are documented in
[`release/fresh-install-acceptance.md`](release/fresh-install-acceptance.md).

## Update procedure

```bash
git pull
docker compose build backend session-agent frontend
docker compose up -d
docker exec <backend-container> alembic upgrade head
docker compose restart reverse-proxy   # nginx caches upstream container IPs at worker start
```

Take a backup first (`./scripts/backup.sh`) — migrations in this project are additive where possible (see the Alembic-gotchas notes in `docs/development.md`), but a backup taken immediately before an update is the cheapest insurance against the one that isn't.

**Upgrading from a deployment older than v1.0.1**: `.env` needs a new required line before `docker compose up -d` above will start `session-agent` at all —

```bash
grep -q '^OPENRBI_DOCKER_SOCKET_GID=' .env || echo "OPENRBI_DOCKER_SOCKET_GID=$(stat -c '%g' /var/run/docker.sock)" >> .env
```

Without it, `docker compose up -d` fails immediately with a clear error naming the missing variable — rather than `session-agent` starting and silently being unable to reach `/var/run/docker.sock`, which is what actually happened on every deployment before this was found (via a real upgrade-acceptance run on genuine infrastructure) and fixed. See the `group_add` comment on `session-agent` in `docker-compose.yml` for the full story.

## Compact vs. Segmented (Productization v0.1.1)

See [ADR 0011](adr/0011-user-admin-listener-separation.md) and [ADR 0012](adr/0012-compact-vs-segmented-deployment.md) for the full reasoning. Two deployment profiles exist, from the same codebase and image:

### Compact

Everything above on this page already describes Compact — it's the default, requires no `OPENRBI_LISTENER_MODE` setting (implicitly `both`), and is the only profile with a complete production guide today (TLS, firewall, backup/restore, update procedure, all above). Recommended for homelab, evaluation, development, and any deployment that doesn't have a specific reason to run two backend processes.

### Segmented — **experimental / technology preview**, not a complete production guide

```
OPENRBI_LISTENER_MODE=user    →  a "User API" process instance
OPENRBI_LISTENER_MODE=admin   →  an "Admin API" process instance
```

`docker-compose.segmented.yml` is a tested, additive overlay that runs both alongside (not instead of) the base `backend` service, for experimentation:

```bash
docker compose -f docker-compose.yml -f docker-compose.segmented.yml \
  up -d backend-user backend-admin
```

What this **does** give you today: a `backend-user` process where `/admin/*` genuinely does not exist (verified: a plain `404`, not a role-check rejection — see `scripts/test-listener-modes.sh`), and a `backend-admin` process where the user-facing session/file/display routes don't exist. What this **does not yet** give you, and would need further work before being a real production Segmented deployment:

- **Separate reverse-proxy origins** — e.g. `https://browser.example.org` for the User API/Portal and `https://admin.example.internal` for the Admin API/Portal, each its own nginx vhost/TLS certificate, the admin one reachable only from a management network. Not wired up; `docker-compose.segmented.yml`'s two backend instances currently have no dedicated proxy path of their own.
- **Separate Postgres roles** — both instances still connect with the same DB credentials/grants today. A `user-api` role with no access to admin-only tables/columns (role assignments, other users' TOTP secrets) is a documented, not-yet-implemented hardening option.
- **Session Agent token scoping** — both instances hold the same shared `OPENRBI_SESSION_AGENT_API_TOKEN`. Per-listener tokens/scopes (so a compromised `backend-user` can't issue `isolate`/`terminate` on arbitrary sessions) are documented, not implemented.
- **Firewall/VLAN enforcement** — entirely an operator decision once real separate origins exist; nothing in this repository automates it, on purpose (see the Productization v0.1.1 analysis's explicit anti-overengineering guardrail).
- **The display relay no longer runs through the backend at all** (Roadmap B2.4, [ADR 0024](adr/0024-cross-host-display-relay.md)) — it terminates at the Session Agent, which is neither `backend-user` nor `backend-admin`. `scripts/setup-network-isolation.sh`'s exemption (`OPENRBI_AGENT_BROWSER_PLANE_IP`, default `172.30.0.2`) is the same in Compact and Segmented alike; nothing about it changes between the two profiles. See [architecture.md#user-portal-and-admin-portal-productization-v011](architecture.md#user-portal-and-admin-portal-productization-v011).

### User Portal and Admin Portal origins

Both portals accept their API base URL at **build time**, via each app's own `.env` (`frontend/user/.env`, `frontend/admin/.env`, see the corresponding `.env.example`):

```bash
# frontend/user/.env
VITE_API_BASE_URL=/api          # Compact default: same-origin, reverse-proxied to backend

# frontend/admin/.env
VITE_API_BASE_URL=/api          # Compact default
```

**Compact** (today's only complete production profile): one reverse-proxy origin serves both — User Portal at `/`, Admin Portal at `/admin/` — both talking to the same `/api` on that same origin, which itself runs `OPENRBI_LISTENER_MODE=both`. This is the default from `frontend/Dockerfile`; no extra configuration needed.

**Segmented** (illustrative, not yet a complete production profile — see above): each portal would get its own origin and point at its own listener, e.g. (using local example names, not real domains):

```bash
# frontend/user/.env  — built for a deployment where the User Portal is DMZ-facing
VITE_API_BASE_URL=https://browser.openrbi.local/api

# frontend/admin/.env — built for a deployment where the Admin Portal is management-side
VITE_API_BASE_URL=https://admin.openrbi.local/api
OPENRBI_ADMIN_BASE_PATH=/        # served at its own origin's root, not /admin/
```

This requires: two reverse-proxy vhosts (one per origin, each with its own TLS certificate), `browser.openrbi.local` pointed at whatever fronts `backend-user`, `admin.openrbi.local` pointed at whatever fronts `backend-admin` (DNS or, for local evaluation, `/etc/hosts` entries on the client machine), and — per the gaps listed above — this is not yet a complete guide: separate DB roles, Session Agent token scoping, and operator-managed firewall/VLAN policy still need to be addressed before treating this as production-grade segmentation rather than a logical/process-level starting point.

## Multi-node — **experimental / technology preview**, not a complete production guide

See [docs/roadmap-b2-multinode.md](roadmap-b2-multinode.md) for the full phase-by-phase design and [ADR 0023](adr/0023-node-enrollment-and-trust-model.md)/[ADR 0024](adr/0024-cross-host-display-relay.md) for the enrollment/trust and cross-host display-relay decisions. Same honesty pattern as Segmented above: this has been verified against a second Session Agent standing in for a second node on the *same* Docker host (every B2 phase's own test suite uses this technique), never against genuinely separate hardware — treat it as a real, working starting point, not a finished multi-host guide.

**Adding a second (or Nth) node:**

1. On the control plane, an ADMIN generates a single-use enrollment token: **Workers → Register node** in the Admin Portal (or `POST /admin/nodes/enrollment-tokens`).
2. On the new host, check out this repository and set up `.env` (same steps as [Installation](#installation) above), plus:
   ```bash
   # Session Agent section of .env
   OPENRBI_AGENT_API_TOKEN=<a real generated secret, distinct from every other node's>
   OPENRBI_AGENT_NODE_NAME=<a stable, distinct name for this node>
   OPENRBI_AGENT_ENROLLMENT_TOKEN=<the token from step 1>
   OPENRBI_AGENT_CONTROL_PLANE_URL=<how this host reaches the control plane>
   OPENRBI_DOCKER_SOCKET_GID=<this host's own docker socket GID>
   ```
3. `docker compose -f docker-compose.node.yml up -d` — this brings up *only* a Session Agent and its own local `browser-plane`, nothing else. It self-enrolls automatically on startup and appears in the Admin Portal's Workers page as `PENDING`.
4. Run `sudo ./scripts/setup-network-isolation.sh` on this host (same as any single-node deployment — see [Network isolation](#network-isolation) above; install the systemd timer too).
5. Back on the control plane, an ADMIN approves the pending node in the Admin Portal (**Workers → Approve**, setting its externally-reachable `endpoint_url`) or revokes it if it shouldn't be trusted. An approved node is immediately schedulable; sessions land on it the same as any other node from that point on.

**What this genuinely requires that no script here automates**, per the roadmap's own explicit "cross-host transport" decision: a private overlay network between the control-plane host and every node host (WireGuard recommended) so `OPENRBI_AGENT_CONTROL_PLANE_URL`/a node's `endpoint_url` are actually reachable. This project validates that a configured endpoint answers and authenticates every call to it — it does not set up or manage that host-to-host connectivity itself, the same boundary already drawn around firewall/VLAN enforcement for Segmented above.

**Removing a node:** revoke it in the Admin Portal (clears its stored token immediately; existing sessions on it are unaffected until they end or fail, per [ADR 0023](adr/0023-node-enrollment-and-trust-model.md)'s and Roadmap B2.5's documented behavior), then `docker compose -f docker-compose.node.yml down` on that host whenever convenient.

## Sizing

Since [Roadmap B3](roadmap-b3-capacity-autoscaling.md), each node's own Session Agent computes its reported capacity from that host's *actual, current* free CPU/RAM headroom — not a flat number an operator sets once and the platform never revisits. This document can't size a fixed number for every deployment (host specs vary too much), but it can explain the reservation model so you can reason about what a given host will support and tune it.

**The model.** Every real poll of `GET /v1/nodes/self` (`session-agent/app/main.py`'s `_compute_capacity()`) reads the host's current free RAM and CPU, divides each by the same per-sandbox reservation the platform already enforces via Docker's own `--cpus`/`--memory` for every sandbox (`OPENRBI_AGENT_DEFAULT_CPU_LIMIT`, default 2.0 CPUs; `OPENRBI_AGENT_DEFAULT_RAM_LIMIT_MB`, default 2048 MB), and reports whichever resource is currently scarcer — a host can be RAM-bound one moment and CPU-bound the next. The Admin Portal's Workers page and Worker Detail show exactly which one is currently binding and the raw numbers behind it (Roadmap B3.3), so you don't have to guess.

- `OPENRBI_AGENT_RESERVED_RAM_MB` (default 512) is held back from the RAM side of that computation for the host OS, the Docker daemon, and the Session Agent process itself — sandboxes are never sized to consume literally every free MB. Raise this on a host also running other workloads alongside OpenRBI.
- `OPENRBI_AGENT_CAPACITY_RECOVERY_POLLS` (default 3) smooths recovery only: a real drop in headroom is reported on the very next poll (fail-closed, by design — a real resource crunch is never hidden), but a rise back up is only reported once this many *consecutive* polls all sustain the higher value, so a momentary spike-then-clear doesn't flap the reported number every poll cycle.
- `OPENRBI_AGENT_CAPACITY` is an optional **ceiling** on the computed value, not the value itself — unset (the default) leaves the real computed number as-is, however high genuine headroom allows. Set it to cap a host below what its real headroom would otherwise support (e.g. to deliberately reserve some slack for other workloads, or to reproduce the pre-B3 fixed-number behavior on a host with more than enough headroom to spare — the ceiling can only ever *lower* the reported number, never raise it above what real headroom actually allows, so it won't recreate the old behavior on a genuinely resource-constrained host).

**Estimating headroom for a new host.** Plan for (number of concurrent sessions you want to support) × (per-sandbox CPU/RAM reservation), plus `OPENRBI_AGENT_RESERVED_RAM_MB`, plus headroom for Postgres/Redis/ClamAV/backend, which are comparatively light — the same math as before B3, just now enforced automatically at run time instead of trusted to an operator-set flat number. Multi-node: the same per-node math applies independently to each node — `select_node()` (Roadmap B2.3) spreads sessions across nodes by free capacity, with no cross-node coordination needed when sizing an individual host.
