# Rollback and recovery

Rollback is backup-based. OpenRBI does not claim zero-downtime or automatic
cross-version database downgrade. A rollback loses writes accepted after the
selected backup, which is why the upgrade runbook requires a write freeze.

## Trigger conditions

Rollback when migration, startup, authentication, file retrieval, sandbox
lifecycle, health, or data-integrity verification fails and cannot be corrected
within the approved maintenance window. Preserve logs and the failed target
containers/images before changing state.

## Procedure

1. Keep user access closed and stop backend/Session Agent processes.
2. Verify the chosen `.sql.gz` and quarantine `.tar.gz` artifacts before any
   destructive restore.
3. Run `scripts/restore.sh` and provide its literal `yes` confirmation only
   after checking the displayed target/artifact paths.
4. Redeploy the exact previously recorded source or image digests and the
   original `.env`. Do not rotate or regenerate encryption keys during recovery.
5. Start PostgreSQL, Valkey and ClamAV, then backend, Session Agent, frontend and
   reverse proxy. Reapply `scripts/setup-network-isolation.sh`.
6. Confirm Alembic revision compatibility. Do not run an improvised downgrade;
   restore the schema/data version paired with the old images.

## Recovery acceptance

Before reopening access, compare the recorded baseline and prove:

- user/policy/security-event/quarantine counts and selected stable IDs;
- quarantine file bytes and SHA-256;
- ADMIN MFA, local login and configured LDAP login;
- one single-use released-file retrieval;
- one real browser create/display/terminate cycle with no leftover sandbox;
- authenticated aggregate health, reverse proxy and both portals.

Record the failed release identity, restored backup identity, data-loss window,
verification output and operator in the incident record. The destructive
backup/restore implementation is continuously exercised by the required
`Backup and restore acceptance` CI job.
