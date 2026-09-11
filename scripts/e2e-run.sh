#!/bin/sh
# Runs the Productization v0.1.1 portal E2E suite (frontend/e2e/) against
# the real, already-running docker compose stack (User Portal + Admin
# Portal + backend + Session Agent + Postgres + Redis + ClamAV) — no mocks,
# matching every other test runner in this project. Run `docker compose up
# -d --build` first.
#
# Seeds two throwaway accounts (e2e_admin, e2e_user) via the real
# create_user() service function, runs Playwright against
# http://localhost:8080 (Compact: User Portal at /, Admin Portal at
# /admin/), then always cleans the accounts (and any sessions/incidents/
# quarantine files/security events they generated) back up — even on
# failure — the same way scripts/run-integration-tests.sh's pytest_ prefix
# is swept up.
set -eu

BACKEND_CONTAINER="${OPENRBI_BACKEND_CONTAINER:-openrbi-backend-1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cleanup() {
    MSYS_NO_PATHCONV=1 docker exec "$BACKEND_CONTAINER" python /app/e2e_seed.py down || true
    MSYS_NO_PATHCONV=1 docker exec -u root "$BACKEND_CONTAINER" rm -f /app/e2e_seed.py || true
}
trap cleanup EXIT

(cd "$SCRIPT_DIR" && MSYS_NO_PATHCONV=1 docker cp "e2e-seed.py" "$BACKEND_CONTAINER:/app/e2e_seed.py")
SEED_JSON=$(MSYS_NO_PATHCONV=1 docker exec "$BACKEND_CONTAINER" python /app/e2e_seed.py up)
echo "seeded: $SEED_JSON"
ADMIN_TOTP_SECRET=$(echo "$SEED_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['admin']['totp_secret'])" 2>/dev/null \
    || echo "$SEED_JSON" | node -e "console.log(JSON.parse(require('fs').readFileSync(0,'utf8')).admin.totp_secret)")

cd "$SCRIPT_DIR/../frontend"
npm install
E2E_BASE_URL="${OPENRBI_E2E_BASE_URL:-http://localhost:8080}" \
E2E_ADMIN_TOTP_SECRET="$ADMIN_TOTP_SECRET" \
    npx playwright test --config=e2e/playwright.config.ts "$@"
