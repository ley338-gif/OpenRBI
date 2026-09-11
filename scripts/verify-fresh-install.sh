#!/bin/sh
# Roadmap Phase B / B1.9 — proves the Definition of Done's core claim for
# real: a genuinely empty database can be turned into a working OpenRBI
# installation with an administrator account, entirely through the API a
# browser would call, with zero manual database access at any point.
#
# Deliberately does NOT touch the shared dev Postgres volume (docker-
# compose.yml's postgres-data) — that's real, possibly-in-use dev data,
# and wiping it to prove a fresh-install claim would be destructive for no
# reason. Instead spins up a throwaway Postgres (its own container/volume)
# and a throwaway backend instance pointed at it (Redis DB index 1 on the
# existing dev Redis, keeping this fully namespace-isolated from real
# session/lockout data on index 0), migrates it from nothing, then drives
# GET /setup/status -> POST /setup/admin -> POST /mfa/setup/enroll ->
# POST /setup/mfa/confirm -> normal /auth/login exactly the way the Admin
# Portal's SetupFlow component does, followed by a real container restart
# to prove persistence (Section 16's explicit second half: "restart and
# confirm setup stays closed, admin can still log in").
set -eu

PG_CONTAINER=openrbi-verify-fresh-pg
BACKEND_CONTAINER=openrbi-verify-fresh-backend
PG_PASSWORD="verify-fresh-throwaway-pw"
TOTP_KEY=$(openssl rand -hex 32)
SESSION_AGENT_TOKEN=$(openssl rand -hex 32)

cleanup() {
    docker rm -f "$BACKEND_CONTAINER" >/dev/null 2>&1 || true
    docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[verify-fresh-install] starting a genuinely empty throwaway Postgres..."
docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$PG_CONTAINER" \
    --network openrbi_control-plane \
    -e POSTGRES_USER=openrbi \
    -e POSTGRES_PASSWORD="$PG_PASSWORD" \
    -e POSTGRES_DB=openrbi \
    postgres:16-alpine >/dev/null

for i in $(seq 1 30); do
    if docker exec "$PG_CONTAINER" pg_isready -U openrbi >/dev/null 2>&1; then break; fi
    sleep 1
done

echo "[verify-fresh-install] running migrations against the empty database..."
docker run --rm \
    --network openrbi_control-plane \
    -e OPENRBI_DATABASE_URL="postgresql+asyncpg://openrbi:$PG_PASSWORD@$PG_CONTAINER:5432/openrbi" \
    -e OPENRBI_REDIS_URL="redis://redis:6379/1" \
    -e OPENRBI_TOTP_SECRET_ENCRYPTION_KEY="$TOTP_KEY" \
    -e OPENRBI_SESSION_AGENT_API_TOKEN="$SESSION_AGENT_TOKEN" \
    openrbi-backend alembic upgrade head

echo "[verify-fresh-install] starting a fresh backend against it..."
docker rm -f "$BACKEND_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$BACKEND_CONTAINER" \
    --network openrbi_control-plane \
    -e OPENRBI_DATABASE_URL="postgresql+asyncpg://openrbi:$PG_PASSWORD@$PG_CONTAINER:5432/openrbi" \
    -e OPENRBI_REDIS_URL="redis://redis:6379/1" \
    -e OPENRBI_TOTP_SECRET_ENCRYPTION_KEY="$TOTP_KEY" \
    -e OPENRBI_SESSION_AGENT_API_TOKEN="$SESSION_AGENT_TOKEN" \
    openrbi-backend >/dev/null

for i in $(seq 1 30); do
    if docker exec "$BACKEND_CONTAINER" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; then break; fi
    sleep 1
done

echo "[verify-fresh-install] GET /setup/status on a fresh install..."
STATUS=$(docker exec "$BACKEND_CONTAINER" python -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://localhost:8000/setup/status'))['setup_required'])")
if [ "$STATUS" != "True" ]; then
    echo "FAIL: fresh install did not report setup_required=true (got: $STATUS)"
    exit 1
fi
echo "  OK: setup_required=true"

TOKEN=$(docker logs "$BACKEND_CONTAINER" 2>&1 | grep -A2 "initial setup token" | tail -1 | tr -d ' \r')
if [ -z "$TOKEN" ]; then
    echo "FAIL: no setup token found in the backend's own console log"
    exit 1
fi
echo "  OK: setup token present in console output (not read from any API or the database)"

echo "[verify-fresh-install] creating the initial administrator via the API..."
docker cp "$(dirname "$0")/verify-fresh-install.py" "$BACKEND_CONTAINER:/tmp/verify_fresh_install.py"
MSYS_NO_PATHCONV=1 docker exec "$BACKEND_CONTAINER" python /tmp/verify_fresh_install.py "$TOKEN"

TOKEN_COUNT_BEFORE_RESTART=$(docker logs "$BACKEND_CONTAINER" 2>&1 | grep -c "initial setup token" || true)

echo "[verify-fresh-install] restarting the backend container..."
docker restart "$BACKEND_CONTAINER" >/dev/null
for i in $(seq 1 30); do
    if docker exec "$BACKEND_CONTAINER" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; then break; fi
    sleep 1
done

echo "[verify-fresh-install] confirming setup stays closed and the admin can still log in..."
STATUS_AFTER_RESTART=$(docker exec "$BACKEND_CONTAINER" python -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://localhost:8000/setup/status'))['setup_required'])")
if [ "$STATUS_AFTER_RESTART" != "False" ]; then
    echo "FAIL: setup reopened after a restart (setup_required=$STATUS_AFTER_RESTART)"
    exit 1
fi
# `docker restart` doesn't truncate prior logs, so compare counts across
# the restart rather than relying on `--since` (wall-clock-relative and
# unreliable when the whole restart+healthcheck loop completes in only a
# few seconds).
TOKEN_COUNT_AFTER_RESTART=$(docker logs "$BACKEND_CONTAINER" 2>&1 | grep -c "initial setup token" || true)
if [ "$TOKEN_COUNT_AFTER_RESTART" != "$TOKEN_COUNT_BEFORE_RESTART" ]; then
    echo "FAIL: a new setup token was logged after restart despite already being initialized (before=$TOKEN_COUNT_BEFORE_RESTART, after=$TOKEN_COUNT_AFTER_RESTART)"
    exit 1
fi
docker cp "$(dirname "$0")/verify-fresh-install-login.py" "$BACKEND_CONTAINER:/tmp/verify_fresh_install_login.py"
MSYS_NO_PATHCONV=1 docker exec "$BACKEND_CONTAINER" python /tmp/verify_fresh_install_login.py

echo "[verify-fresh-install] all checks passed — fresh install to working admin, zero DB access"
