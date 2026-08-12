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

mkdir -p "$OUT_DIR"

echo "[backup] Postgres -> $OUT_DIR/openrbi-db-$STAMP.sql.gz"
# --clean --if-exists so the corresponding restore is idempotent against a
# freshly-initialized (or previously restored) database.
docker exec "$POSTGRES_CONTAINER" pg_dump -U openrbi --clean --if-exists openrbi | gzip > "$OUT_DIR/openrbi-db-$STAMP.sql.gz"

echo "[backup] quarantine-staging volume -> $OUT_DIR/openrbi-quarantine-$STAMP.tar.gz"
# Goes through the backend container (the volume's actual mount point,
# /app/data) rather than a throwaway container, so this works without
# assuming any particular volume driver/host path. MSYS_NO_PATHCONV avoids
# Git-Bash-for-Windows rewriting the container-side /app/data path into a
# host path before it reaches docker; harmless elsewhere.
MSYS_NO_PATHCONV=1 docker exec "$BACKEND_CONTAINER" tar -czf - -C /app/data . > "$OUT_DIR/openrbi-quarantine-$STAMP.tar.gz"

echo "[backup] done:"
ls -lh "$OUT_DIR/openrbi-db-$STAMP.sql.gz" "$OUT_DIR/openrbi-quarantine-$STAMP.tar.gz"
