# Upgrade acceptance

The v1 upgrade gate starts from commit
`2816cfadbcfbf580959b1e78190fd7bbbe47796b` and upgrades its persistent
Compact deployment in place to the commit under test.

## Why this baseline

The repository has no historical Git tag, GitHub Release, or published 0.x
image. The pinned commit is the merge of PR #56: it still identifies as 0.1.1,
had green required CI, includes the completed productization features, and is
the first 0.x commit with exact hash-locked Python dependencies and `npm ci`.
It is therefore the latest reproducibly buildable 0.x candidate available. It
must not be described as a published release.

The target is the exact pull-request/main commit under test. A `1.0.0-rc.N`
tag is intentionally created only after all v1 acceptance work is complete.

## Automated procedure

Run on a clean Linux Docker host:

```bash
sudo chmod 666 /var/run/docker.sock # GitHub-hosted runner workaround only
./scripts/run-upgrade-acceptance.sh
```

The script:

1. Verifies the pinned baseline is an ancestor and exports that exact tree.
2. Builds and starts all four 0.x images with fresh secrets and volumes.
3. Migrates the empty 0.x database, bootstraps the MFA admin, and creates a user.
4. Persists MFA and LDAP secrets, a published policy, terminated session,
   security events, a released quarantine file plus bytes, and worker metrics.
5. Takes and validates database/quarantine backups before changing images.
6. Removes only the old containers and networks, preserving named volumes.
7. Builds all four target images, runs `alembic upgrade head`, and requires one
   current Alembic head.
8. Proves all four image identities changed, then starts the target stack.
9. Verifies stable record identities and encrypted secrets, admin MFA login,
   user login, single-use file download, a real browser session, aggregate
   health, reverse proxy, and both portals.

## Rollback procedure

If an operator upgrade fails:

1. Stop the target `backend` and `session-agent`; retain failure logs.
2. Keep the pre-upgrade `.sql.gz` and quarantine `.tar.gz` artifacts offline.
3. Use the v1 `scripts/restore.sh` to restore both validated artifacts. This is
   destructive and requires the literal `yes` confirmation.
4. Rebuild or redeploy the exact pinned 0.x source/images and the original
   `.env` secrets; never generate a different TOTP encryption key.
5. Start Postgres/Valkey/ClamAV, then backend, Session Agent, frontend and proxy.
6. Reapply `scripts/setup-network-isolation.sh` and repeat login, MFA, download,
   session and health smoke checks before reopening access.

Rollback cannot preserve writes accepted after the pre-upgrade backup. Schedule
an application write freeze before production upgrades.

## Known limitations

- No 0.x registry artifacts exist, so CI builds the pinned source tree instead
  of pulling a historical signed/published image.
- The baseline and current candidate presently share the same Alembic head; the
  gate proves migration invocation/head integrity and persistent-state/image
  replacement, but does not fabricate a schema delta that never existed.
- Compact single-host Docker is the only supported v1 upgrade path. Segmented,
  multi-host, HA, Kubernetes, and cross-architecture upgrades are not covered.
- The gate uses generated test secrets and synthetic directory configuration;
  it does not contact an organization's real LDAP server.
