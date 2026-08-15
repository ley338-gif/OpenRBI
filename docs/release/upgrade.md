# Supported v1 upgrade runbook

Compact single-host Docker is the only supported v1 upgrade path. The automated
qualification from the pinned 0.1.1 source is documented in
[`upgrade-acceptance.md`](upgrade-acceptance.md); this page is the operator
procedure.

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

## Upgrade

```bash
git fetch --tags origin
git checkout <accepted-v1-tag-or-commit>
docker compose build backend session-agent frontend
docker compose up -d postgres redis clamav
docker compose run --rm backend alembic upgrade head
docker compose up -d backend session-agent frontend reverse-proxy
docker build -t openrbi-browser:latest -f docker/browser/Dockerfile docker/browser
sudo ./scripts/setup-network-isolation.sh
```

For published releases, deploy the recorded image digests instead of rebuilding
source locally. Never use an unqualified floating `latest` tag as proof of
identity.

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
