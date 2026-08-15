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

docker compose up -d --build

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

Without this timer (or an equivalent host-level automation you set up yourself), re-run `sudo ./scripts/setup-network-isolation.sh` manually after every: host reboot, Docker daemon restart, `docker compose down && up` that recreates the `browser-plane` network, and any change to `OPENRBI_BROWSER_PLANE_NETWORK`/`OPENRBI_BACKEND_BROWSER_PLANE_IP`. `./scripts/setup-network-isolation.sh --remove` clears both the iptables rules and the marker file (health immediately reports `NOT_CONFIGURED`, never a stale `HEALTHY`).

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

```bash
./scripts/restore.sh <db-dump.sql.gz> <quarantine.tar.gz>
```

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
- **The display relay's `browser-plane` exemption defaults to the base `backend` service only.** `scripts/setup-network-isolation.sh` now accepts `OPENRBI_BACKEND_BROWSER_PLANE_IP` as a space-separated list, so a Segmented deployment can exempt `backend-user`'s own pinned address (`172.30.0.4`, the process that actually terminates `/display/*/ws` in this profile) instead of Compact's default:
  ```bash
  OPENRBI_BACKEND_BROWSER_PLANE_IP="172.30.0.4" sudo -E ./scripts/setup-network-isolation.sh
  ```
  `backend-admin` deliberately has no `browser-plane` network attachment and gets no exemption — it never terminates the display route, so it never needs one. See [architecture.md#user-portal-and-admin-portal-productization-v011](architecture.md#user-portal-and-admin-portal-productization-v011).

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

This requires: two reverse-proxy vhosts (one per origin, each with its own TLS certificate), `browser.openrbi.local` pointed at whatever fronts `backend-user`, `admin.openrbi.local` pointed at whatever fronts `backend-admin` (DNS or, for local evaluation, `/etc/hosts` entries on the client machine), and — per the gaps listed above — this is not yet a complete guide: separate DB roles, Session Agent token scoping, and operator-managed firewall/VLAN policy still need to be addressed before treating this as production-grade segmentation rather than a logical/process-level starting point. The display relay's browser-plane address can already be selected explicitly with `OPENRBI_BACKEND_BROWSER_PLANE_IP`, as shown above.

## Sizing

MVP 1 has no host-resource-aware scheduler (see [architecture.md#multi-node-readiness](architecture.md#multi-node-readiness)) — capacity is a fixed ceiling (`session-agent`'s `default_cpu_limit`/`default_ram_limit_mb`, currently 2 CPUs / 2 GB per sandbox), not something this document can size for every deployment. As a starting point: plan for (number of concurrent sessions you want to support) × (per-sandbox CPU/RAM limit), plus headroom for Postgres/Redis/ClamAV/backend, which are comparatively light.
