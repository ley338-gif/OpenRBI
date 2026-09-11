#!/bin/sh
# Roadmap Phase A / A6 — rotates OPENRBI_TOTP_SECRET_ENCRYPTION_KEY,
# re-encrypting every stored TOTP secret from the old key to a new one
# first (see backend/scripts/rotate_totp_key.py's module docstring for why
# this can't just be an .env edit + restart). Run against the real,
# already-running docker compose stack.
#
# Usage:
#   ./scripts/rotate-totp-key.sh <old-key> <new-key>     # dry run first
#   ./scripts/rotate-totp-key.sh <old-key> <new-key> --apply
#
# Generate <new-key> with: openssl rand -hex 32
set -eu

BACKEND_CONTAINER="${OPENRBI_BACKEND_CONTAINER:-openrbi-backend-1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

OLD_KEY="${1:?usage: $0 <old-key> <new-key> [--apply]}"
NEW_KEY="${2:?usage: $0 <old-key> <new-key> [--apply]}"
APPLY_FLAG="${3:-}"

docker cp "$SCRIPT_DIR/../backend/scripts/rotate_totp_key.py" "$BACKEND_CONTAINER:/app/rotate_totp_key.py"

# MSYS_NO_PATHCONV avoids Git-Bash-for-Windows rewriting these
# container-side /app paths into host paths before they reach docker;
# harmless elsewhere (same pattern as scripts/run-integration-tests.sh).
if [ "$APPLY_FLAG" = "--apply" ]; then
    echo "[rotate-totp-key] APPLYING — this commits re-encrypted secrets."
    MSYS_NO_PATHCONV=1 docker exec "$BACKEND_CONTAINER" python /app/rotate_totp_key.py --old-key "$OLD_KEY" --new-key "$NEW_KEY"
else
    echo "[rotate-totp-key] Dry run (pass --apply as the third argument to commit)."
    MSYS_NO_PATHCONV=1 docker exec "$BACKEND_CONTAINER" python /app/rotate_totp_key.py --old-key "$OLD_KEY" --new-key "$NEW_KEY" --dry-run
fi

MSYS_NO_PATHCONV=1 docker exec -u root "$BACKEND_CONTAINER" rm -f /app/rotate_totp_key.py

echo
echo "[rotate-totp-key] If this was a real (--apply) run and it succeeded:"
echo "  1. Update OPENRBI_TOTP_SECRET_ENCRYPTION_KEY=$NEW_KEY in .env on every host running backend."
echo "  2. Restart backend: docker compose up -d backend"
echo "  Do this promptly — until step 2, backend is still running with the OLD key configured"
echo "  while the DB now holds secrets encrypted under the NEW key, so MFA verification will fail"
echo "  for every user in that window."
