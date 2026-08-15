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
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
APP_STOPPED=0

compose() {
    docker compose --project-directory "$REPO_ROOT" -f "$REPO_ROOT/docker-compose.yml" "$@"
}

restart_services() {
    if [ "$APP_STOPPED" -eq 1 ]; then
        compose start backend session-agent >/dev/null 2>&1 || true
    fi
}
trap restart_services EXIT HUP INT TERM

for archive in "$DB_DUMP" "$QUARANTINE_TAR"; do
    if [ ! -r "$archive" ] || [ ! -s "$archive" ]; then
        echo "backup artifact is missing, unreadable, or empty: $archive" >&2
        exit 1
    fi
done
gzip -t "$DB_DUMP"
tar -tzf "$QUARANTINE_TAR" >/dev/null
if ! tar -tzf "$QUARANTINE_TAR" | awk '
    /^\// { exit 1 }
    { count = split($0, parts, "/"); for (i = 1; i <= count; i++) if (parts[i] == "..") exit 1 }
'; then
    echo "quarantine archive contains an unsafe path" >&2
    exit 1
fi

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

echo "[restore] stopping backend/session-agent so nothing writes during the database restore..."
compose stop backend session-agent >/dev/null
APP_STOPPED=1

echo "[restore] quarantine storage..."
MSYS_NO_PATHCONV=1 compose run --rm --no-deps -T --entrypoint sh backend -c \
    'find /app/data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +'
MSYS_NO_PATHCONV=1 compose run --rm --no-deps -T --entrypoint tar backend \
    -xzf - -C /app/data < "$QUARANTINE_TAR"

echo "[restore] database..."
# The dump was produced with --clean --if-exists (scripts/backup.sh), so
# this drops and recreates every object it contains — safe to run against
# a database that already has the same (or an older) schema in place.
gunzip -c "$DB_DUMP" | docker exec -i "$POSTGRES_CONTAINER" psql -U openrbi -d openrbi

echo "[restore] starting backend/session-agent..."
compose start backend session-agent >/dev/null
APP_STOPPED=0
compose restart reverse-proxy >/dev/null
trap - EXIT HUP INT TERM

# RBI-POST-018: a light functional sanity check, not a substitute for the
# real end-to-end validation in scripts/run-backup-restore-acceptance.sh
# (exact record/byte comparison against a known baseline) — deliberately
# no checksum database or per-file verification here, just "did the
# restore actually leave a working, migrated, queryable database and a
# reachable quarantine volume" before handing control back to the
# operator. A failure here is a strong signal something's wrong; success
# is not itself proof the data is correct, only that it's there.
echo "[restore] verifying database is reachable and migrated..."
for i in $(seq 1 30); do
    if docker exec "$POSTGRES_CONTAINER" pg_isready -U openrbi -d openrbi >/dev/null 2>&1; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[restore] WARNING: PostgreSQL did not become ready within 30s after restore — verify manually" >&2
    fi
    sleep 1
done
if ! docker exec "$POSTGRES_CONTAINER" psql -U openrbi -d openrbi -tAc \
    "SELECT 1 FROM users LIMIT 1" >/dev/null 2>&1; then
    echo "[restore] WARNING: could not read the 'users' table after restore — schema may not match this backup (run alembic upgrade head, see docs/deployment.md#update-procedure)" >&2
fi
if ! MSYS_NO_PATHCONV=1 compose exec -T backend sh -c 'test -d /app/data' >/dev/null 2>&1; then
    echo "[restore] WARNING: quarantine storage volume is not accessible from the backend container after restore" >&2
fi

echo "[restore] done; reverse proxy restarted. Run alembic upgrade if this backup predates the current schema (docs/deployment.md#update-procedure)."
