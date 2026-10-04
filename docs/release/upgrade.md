# Supported v1 upgrade runbook

Compact single-host Docker is the only supported v1 upgrade path. This page is
the operator procedure.

## Qualification

The automated `Upgrade acceptance` gate upgrades two baselines to the release
candidate: a pinned 0.1.1 installation, and the previous GA release (e.g. 1.0.2
→ 1.0.3) — see [`upgrade-acceptance.md`](upgrade-acceptance.md). Upgrading
across several releases at once runs the same migrations and procedure but is
not tested as its own path. In every case read the release-specific notes
first: the **Breaking** entries under **Changed** in
[`CHANGELOG.md`](../../CHANGELOG.md) for every version you skip, summarized in
[`deployment.md`](../deployment.md#update-procedure).

## Before the change

1. Confirm the target commit/tag passed its own `Release gates` check and is
   covered by [`v1-acceptance.md`](v1-acceptance.md).
2. Schedule a write freeze. Backups cannot retain writes accepted afterward.
3. Record current image digests, `.env` location/permissions, Alembic revision,
   aggregate health and table/file counts needed for verification.
4. Run `scripts/backup.sh`; validate both the database `.sql.gz` and quarantine
   `.tar.gz`; copy them off-host.
5. Preserve every existing secret, especially
   `OPENRBI_TOTP_SECRET_ENCRYPTION_KEY`. Generating a replacement during an
   upgrade makes enrolled MFA and encrypted LDAP credentials unreadable.
6. Apply the release-specific changes the CHANGELOG's **Breaking** entries ask
   for (renamed or newly required `.env` settings, re-running
   `scripts/provision-segmented-db-roles.sh` for an opted-in Segmented
   deployment, …) before starting the new version.

## Upgrade

The supported upgrade is one idempotent command:
`git fetch --tags origin && git checkout <tag> && sudo ./scripts/deploy.sh`. It
runs exactly this sequence; use the individual commands only to repeat a single
step by hand:

```bash
git fetch --tags origin
git checkout <accepted-v1-tag-or-commit>
./scripts/backup.sh                      # deploy.sh does this first (--no-backup skips it)
docker compose pull --ignore-buildable   # refresh postgres/valkey/clamav/nginx under the same tags
./scripts/build.sh                       # backend, session-agent, frontend: --pull, real version metadata
docker compose up -d postgres redis clamav
docker compose run --rm backend alembic upgrade head
docker compose up -d
./scripts/build-browser-image.sh         # --pull --no-cache: Debian's current Firefox ESR security release
docker compose restart reverse-proxy
./scripts/seed-standard-policies.sh      # only templates new to this installation
sudo ./scripts/setup-network-isolation.sh
```

Do not shorten this to a plain `docker compose build` or a cached
`docker build` of the browser image: both reuse stale base layers, and a cached
browser build keeps shipping the previously installed Firefox ESR.

The procedure builds the images from the tagged source. Running the
release-published GHCR images instead is not wired into `docker-compose.yml` or
`deploy.sh`; if you do, pin each image by the registry digest recorded in that
release's `release-metadata.json` and verify its OCI version/revision labels.
Never use a floating tag as proof of identity — releases deliberately publish
no `latest`.

## Verification before reopening access

- `alembic current` reports exactly the release head.
- `/health` is live and authenticated `/admin/health` reports expected
  components.
- Existing ADMIN MFA and local/LDAP user login work.
- Existing policies, security events and quarantine metadata/bytes are present.
- A released file can be retrieved with a single-use token.
- A new real browser session starts and terminates with no leftover container.
- Both portals and the reverse proxy respond over the production TLS origin.

If any check fails, keep the write freeze and follow [`rollback.md`](rollback.md).
