#!/bin/sh
# Phase 22 (Deployment): backs up everything that isn't reproducible by
# just re-running docker compose — the Postgres database (all app state:
# users, policies, sessions, incidents, audit log) and the quarantine
# staging volume (files awaiting or already past review). Never persisted
# browser data (profiles, cookies, history) is intentionally excluded —
# there is none to back up (ADR 0007).
#
# Usage: ./scripts/backup.sh [output-directory]   (default: ./backups)
set -eu

POSTGRES_CONTAINER="${OPENRBI_POSTGRES_CONTAINER:-openrbi-postgres-1}"
BACKEND_CONTAINER="${OPENRBI_BACKEND_CONTAINER:-openrbi-backend-1}"
OUT_DIR="${1:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DB_FILE="$OUT_DIR/openrbi-db-$STAMP.sql.gz"
QUARANTINE_FILE="$OUT_DIR/openrbi-quarantine-$STAMP.tar.gz"
RAW_DB="$OUT_DIR/.openrbi-db-$STAMP.sql.part.$$"
TMP_DB="$DB_FILE.part.$$"
TMP_QUARANTINE="$QUARANTINE_FILE.part.$$"

cleanup() {
    rm -f -- "$RAW_DB" "$TMP_DB" "$TMP_QUARANTINE"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$OUT_DIR"

echo "[backup] Postgres -> $DB_FILE"
# --clean --if-exists so the corresponding restore is idempotent against a
# freshly-initialized (or previously restored) database.
docker exec "$POSTGRES_CONTAINER" pg_dump -U openrbi --clean --if-exists openrbi > "$RAW_DB"
gzip -c "$RAW_DB" > "$TMP_DB"
gzip -t "$TMP_DB"
[ -s "$TMP_DB" ]
mv "$TMP_DB" "$DB_FILE"
rm -f -- "$RAW_DB"

echo "[backup] quarantine-staging volume -> $QUARANTINE_FILE"
# Goes through the backend container (the volume's actual mount point,
# /app/data) rather than a throwaway container, so this works without
# assuming any particular volume driver/host path. MSYS_NO_PATHCONV avoids
# Git-Bash-for-Windows rewriting the container-side /app/data path into a
# host path before it reaches docker; harmless elsewhere.
MSYS_NO_PATHCONV=1 docker exec "$BACKEND_CONTAINER" tar -czf - -C /app/data . > "$TMP_QUARANTINE"
tar -tzf "$TMP_QUARANTINE" >/dev/null
[ -s "$TMP_QUARANTINE" ]
mv "$TMP_QUARANTINE" "$QUARANTINE_FILE"

echo "[backup] done:"
ls -lh "$DB_FILE" "$QUARANTINE_FILE"
