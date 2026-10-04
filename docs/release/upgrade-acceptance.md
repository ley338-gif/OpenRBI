# Upgrade acceptance

The upgrade gate builds a persistent Compact deployment of a baseline
version, fills it with real state, and upgrades it in place to the commit under
test. It runs for two baselines, as two legs of the `Upgrade acceptance` job:

| Leg | Baseline | Selected by |
|---|---|---|
| `Upgrade acceptance (from 0.1.1)` | commit `2816cfadbcfbf580959b1e78190fd7bbbe47796b` | default (`OPENRBI_UPGRADE_BASELINE` unset) |
| `Upgrade acceptance (from previous release)` | the newest GA tag (`vX.Y.Z`) in the history that does not point at the commit under test — for a change on `main` after 1.0.2 that is `v1.0.2`; for an acceptance run of the `v1.0.2` tag itself it is `v1.0.1` | `OPENRBI_UPGRADE_BASELINE=previous-release` |

Any other tag or commit can be passed as `OPENRBI_UPGRADE_BASELINE` for a manual
run. The target is the exact pull-request/main commit under test (or, in
`acceptance-published.yml`, the published images of the accepted release).

## Why these baselines

**0.1.1** is the oldest supported source of an upgrade to v1. The repository
has no 0.x tag, GitHub Release or published 0.x image; the pinned commit is the
merge of PR #56. It still identifies as 0.1.1, had green required CI, includes
the completed productization features, and is the first 0.x commit with exact
hash-locked Python dependencies and `npm ci`, so it is the latest reproducibly
buildable 0.x candidate. It must not be described as a published release.

**The previous release** is what existing installations run today, so it is
the upgrade every release actually has to support. Its migrations and data
model are the closest to the candidate's, which is where a schema change, a
renamed setting or a data migration bug would show up first.

Both baselines are built from their own source, the same way
`scripts/deploy.sh` deploys. The fixture and verification helpers
(`scripts/fresh-install-acceptance.py`, `backup-restore-acceptance.py`,
`upgrade-acceptance.py`) come from the commit under test and run against the
baseline's application code, so they have to stay compatible with the previous
release; a change that breaks that fails the gate.

## Automated procedure

Run on a clean Linux Docker host:

```bash
sudo chmod 666 /var/run/docker.sock # GitHub-hosted runner workaround only
./scripts/run-upgrade-acceptance.sh                                         # from 0.1.1
OPENRBI_UPGRADE_BASELINE=previous-release ./scripts/run-upgrade-acceptance.sh
```

The previous-release leg needs the release tags in the checkout (a full clone,
or `fetch-depth: 0` in Actions).

The script:

1. Resolves the baseline, verifies it is an ancestor and exports that exact tree.
2. Builds and starts all four baseline images with fresh secrets and volumes.
3. Migrates the empty baseline database, bootstraps the MFA admin, and creates a user.
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
   destructive and requires the literal `yes` confirmation. `restore.sh`
   restarts the existing (failed target) `backend`/`session-agent` containers
   when it finishes; stop them again before the next step.
4. Rebuild or redeploy the exact previous source/images (the baseline release)
   and the original `.env` secrets; never generate a different TOTP encryption key.
5. Start Postgres/Valkey/ClamAV, then backend, Session Agent, frontend and proxy.
6. Reapply `scripts/setup-network-isolation.sh` and repeat login, MFA, download,
   session and health smoke checks before reopening access.

Rollback cannot preserve writes accepted after the pre-upgrade backup. Schedule
an application write freeze before production upgrades.

## Known limitations

- Both baselines are built from source, not pulled as published images: no
  0.x registry artifacts exist, and the supported deployment path builds from
  source anyway.
- Only two upgrade paths are exercised: 0.1.1 → candidate and previous GA
  release → candidate. Skipping several v1 releases at once (e.g. 1.0.0 →
  candidate) is not tested separately; it runs the same migrations, but read
  every skipped release's **Breaking** CHANGELOG entries.
- The previous-release leg was added after 1.0.2, so no release up to and
  including 1.0.2 was accepted against it.
- Compact single-host Docker is the only supported v1 upgrade path. Segmented,
  multi-host, HA, Kubernetes, and cross-architecture upgrades are not covered.
- The gate uses generated test secrets and synthetic directory configuration;
  it does not contact an organization's real LDAP server.
