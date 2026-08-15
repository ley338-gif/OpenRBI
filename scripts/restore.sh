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

echo "[restore] done; reverse proxy restarted. Run alembic upgrade if this backup predates the current schema (docs/deployment.md#update-procedure)."
