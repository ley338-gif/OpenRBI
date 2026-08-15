# Backup and restore acceptance

`scripts/run-backup-restore-acceptance.sh` is the v1 release gate for the
existing `scripts/backup.sh` and `scripts/restore.sh` workflow. It requires a
clean Linux Docker host and refuses to reuse an existing Compose project or
overwrite a repository `.env` file.

The gate performs a real current-schema recovery, not only an exit-code check:

1. Builds an isolated Compact installation and migrates an empty database.
2. Creates the initial MFA administrator and a local user through the public API.
3. Seeds a published policy, an append-only security event, quarantine metadata,
   and content-addressed quarantine bytes through application models/services.
4. Records counts for every mapped application table and stable identifiers for
   the concrete evidence records.
5. Runs the production backup script and validates both compressed artifacts.
6. Corrupts the user and policy, deletes the evidence event and quarantine row,
   and overwrites the staged bytes.
7. Runs the production restore script with its destructive confirmation.
8. Requires exact table-count equality and verifies the identified user, policy
   version, audit event, quarantine metadata, file contents, and SHA-256.
9. Logs in with the restored local account and starts/terminates a real sandbox.
10. Requires the reverse proxy, user portal, admin portal, and health endpoint to
    respond after recovery, then removes the isolated project and its volumes.

Run it from a clean checkout:

```bash
sudo chmod 666 /var/run/docker.sock # only when the host's docker group is not gid 0
./scripts/run-backup-restore-acceptance.sh
```

The Docker-socket permission workaround is needed on GitHub-hosted runners. A
production host should instead grant the hardened session-agent's uid/gid only
the access required by the chosen container-runtime policy.

The acceptance evidence is emitted as `ACCEPT BR-*` lines, including the full
baseline table-count map. Any mismatch, missing record, changed byte, failed
login/session, unhealthy endpoint, or leftover sandbox fails the release gate.
