#!/bin/sh
# Phase 22 (Deployment): restores a backup produced by scripts/backup.sh.
# DESTRUCTIVE — overwrites the live database and quarantine storage.
# Intended for disaster recovery, not routine use.
#
# Usage: ./scripts/restore.sh <db-dump.sql.gz> <quarantine.tar.gz>
set -eu

if [ "$#" -ne 2 ]; then
    echo "usage: $0 <db-dump.sql.gz> <quarantine.tar.gz>" >&2
    exit 1
fi

DB_DUMP="$1"
QUARANTINE_TAR="$2"
POSTGRES_CONTAINER="${OPENRBI_POSTGRES_CONTAINER:-openrbi-postgres-1}"
BACKEND_CONTAINER="${OPENRBI_BACKEND_CONTAINER:-openrbi-backend-1}"

echo "About to restore:"
echo "  database  <- $DB_DUMP"
echo "  quarantine storage <- $QUARANTINE_TAR"
echo "This OVERWRITES the current database and quarantine storage on the running stack."
printf "Type 'yes' to continue: "
read -r CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "aborted."
    exit 1
fi

# Quarantine storage is restored first, while the backend container is
# still up — `docker exec` needs a running container, and stopping the app
# process (below, for the database step) does not mean stopping the
# container. The brief window where the app is up but its files are being
# swapped underneath it is the accepted tradeoff; it's a short tar
# extraction, not a long-running risk.
echo "[restore] quarantine storage..."
MSYS_NO_PATHCONV=1 docker exec -i "$BACKEND_CONTAINER" sh -c 'rm -rf /app/data/* /app/data/.[!.]*' 2>/dev/null || true
MSYS_NO_PATHCONV=1 docker exec -i "$BACKEND_CONTAINER" tar -xzf - -C /app/data < "$QUARANTINE_TAR"

echo "[restore] stopping backend/session-agent so nothing writes during the database restore..."
docker compose stop backend session-agent >/dev/null

echo "[restore] database..."
# The dump was produced with --clean --if-exists (scripts/backup.sh), so
# this drops and recreates every object it contains — safe to run against
# a database that already has the same (or an older) schema in place.
gunzip -c "$DB_DUMP" | docker exec -i "$POSTGRES_CONTAINER" psql -U openrbi -d openrbi

echo "[restore] starting backend/session-agent..."
docker compose start backend session-agent >/dev/null

echo "[restore] done. Run alembic upgrade if this backup predates the current schema (docs/deployment.md#update-procedure)."
