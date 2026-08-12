# Deployment

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

At this point the stack is reachable on `http://<host>:8080` — fine for local evaluation, **not** for any real deployment (no TLS, session cookies never get `Secure`, port 8080 rather than 443). Continue below for an actual deployment.

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

## Backup and restore

```bash
./scripts/backup.sh [output-directory]     # default: ./backups
```

Produces a gzip'd `pg_dump` (built with `--clean --if-exists`, so restoring it is idempotent against a database that already has the same or an older schema) and a gzip'd tarball of the `quarantine-staging` volume, both timestamped.

```bash
./scripts/restore.sh <db-dump.sql.gz> <quarantine.tar.gz>
```

**Destructive** — overwrites the live database and quarantine storage. Asks for an explicit `yes` before doing anything. Stops `backend`/`session-agent` for the database restore (nothing should be querying mid-restore) and restarts them afterward. If the backup predates the current schema, run the [update procedure](#update-procedure)'s `alembic upgrade head` step afterward.

Verified end-to-end against the live stack: a real backup taken, restored back over the running system, and the user/security-event counts confirmed unchanged afterward.

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

### Segmented — preparatory, **not yet a complete production guide**

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
- **The display relay's network exemption** — `scripts/setup-network-isolation.sh`'s allow-list is hardcoded to the base `backend` service's pinned `browser-plane` address; `backend-user`'s own pinned address (see the overlay file's comments) is not yet exempted, so a real deployment running the display relay from `backend-user` instead of `backend` would need that script updated first — deliberately not done in this pass (see [ADR 0013](adr/0013-browser-isolation-zone.md); browser-plane itself is unchanged by this work).
- **Firewall/VLAN enforcement** — entirely an operator decision once real separate origins exist; nothing in this repository automates it, on purpose (see the Productization v0.1.1 analysis's explicit anti-overengineering guardrail).

## Sizing

MVP 1 has no host-resource-aware scheduler (see [architecture.md#multi-node-readiness](architecture.md#multi-node-readiness)) — capacity is a fixed ceiling (`session-agent`'s `default_cpu_limit`/`default_ram_limit_mb`, currently 2 CPUs / 2 GB per sandbox), not something this document can size for every deployment. As a starting point: plan for (number of concurrent sessions you want to support) × (per-sandbox CPU/RAM limit), plus headroom for Postgres/Redis/ClamAV/backend, which are comparatively light.
