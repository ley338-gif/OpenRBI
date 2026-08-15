#!/bin/sh
# Destructive reliability acceptance for an isolated Docker Compose test stack.
# Never point the OPENRBI_*_CONTAINER overrides at production resources.
set -eu

BACKEND_CONTAINER="${OPENRBI_BACKEND_CONTAINER:-openrbi-backend-1}"
SESSION_AGENT_CONTAINER="${OPENRBI_SESSION_AGENT_CONTAINER:-openrbi-session-agent-1}"
POSTGRES_CONTAINER="${OPENRBI_POSTGRES_CONTAINER:-openrbi-postgres-1}"
REDIS_CONTAINER="${OPENRBI_REDIS_CONTAINER:-openrbi-redis-1}"
CLAMAV_CONTAINER="${OPENRBI_CLAMAV_CONTAINER:-openrbi-clamav-1}"
CONTROL_PLANE_NETWORK="${OPENRBI_CONTROL_PLANE_NETWORK:-openrbi_control-plane}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
START_LOG="/tmp/openrbi-startup-fault.log"
HOST_PYTHON="${OPENRBI_HOST_PYTHON:-python3}"

json_field() {
    "$HOST_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}

wait_backend() {
    i=0
    until docker exec "$BACKEND_CONTAINER" python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" \
        >/dev/null 2>&1; do
        i=$((i + 1)); [ "$i" -lt 40 ] || { echo "backend recovery timed out" >&2; return 1; }
        sleep 1
    done
}

wait_agent() {
    i=0
    until docker exec "$BACKEND_CONTAINER" python -c \
        "import urllib.request; urllib.request.urlopen('http://session-agent:8100/health', timeout=2)" \
        >/dev/null 2>&1; do
        i=$((i + 1)); [ "$i" -lt 40 ] || { echo "session-agent recovery timed out" >&2; return 1; }
        sleep 1
    done
}

restore_dependencies() {
    docker start "$POSTGRES_CONTAINER" "$REDIS_CONTAINER" "$CLAMAV_CONTAINER" >/dev/null 2>&1 || true
    docker start "$SESSION_AGENT_CONTAINER" >/dev/null 2>&1 || true
    if ! docker inspect "$SESSION_AGENT_CONTAINER" --format \
        "{{with index .NetworkSettings.Networks \"$CONTROL_PLANE_NETWORK\"}}{{.IPAddress}}{{end}}" \
        2>/dev/null | grep -q .; then
        docker compose up -d --force-recreate session-agent >/dev/null 2>&1 || true
    fi
}
trap restore_dependencies EXIT INT TERM

docker cp "$SCRIPT_DIR/fault-injection-probe.py" "$BACKEND_CONTAINER:/tmp/fault-injection-probe.py"
probe() {
    MSYS_NO_PATHCONV=1 docker exec -e PYTHONPATH=/app "$BACKEND_CONTAINER" \
        python /tmp/fault-injection-probe.py "$@"
}

echo "== Fault 1: docker kill Browser Sandbox =="
SEED_ONE=$(probe seed-active)
SESSION_ONE=$(printf '%s' "$SEED_ONE" | json_field session_id)
TOKEN_ONE=$(printf '%s' "$SEED_ONE" | json_field login_token)
docker kill "openrbi-session-$SESSION_ONE" >/dev/null
probe reconcile-lost "$SESSION_ONE"
if docker inspect "openrbi-session-$SESSION_ONE" >/dev/null 2>&1; then
    echo "hard-killed browser container still exists" >&2
    exit 1
fi

echo "== Fault 2: docker kill Session Agent =="
SEED_TWO=$(probe seed-active)
SESSION_TWO=$(printf '%s' "$SEED_TWO" | json_field session_id)
TOKEN_TWO=$(printf '%s' "$SEED_TWO" | json_field login_token)
docker kill "$SESSION_AGENT_CONTAINER" >/dev/null
test "$(docker inspect "$SESSION_AGENT_CONTAINER" --format '{{.State.Status}}')" = "exited"
probe agent-unavailable
docker start "$SESSION_AGENT_CONTAINER" >/dev/null
wait_agent
probe verify-active "$SESSION_TWO" "$TOKEN_TWO"

echo "== Fault 3: docker restart Backend =="
docker restart "$BACKEND_CONTAINER" >/dev/null
wait_backend
docker cp "$SCRIPT_DIR/fault-injection-probe.py" "$BACKEND_CONTAINER:/tmp/fault-injection-probe.py"
probe verify-active "$SESSION_TWO" "$TOKEN_TWO"

echo "== Fault 4: docker restart PostgreSQL =="
docker restart "$POSTGRES_CONTAINER" >/dev/null
i=0
until docker exec "$POSTGRES_CONTAINER" pg_isready -U openrbi -d openrbi >/dev/null 2>&1; do
    i=$((i + 1)); [ "$i" -lt 40 ] || { echo "postgres recovery timed out" >&2; exit 1; }
    sleep 1
done
# Retry once after a stale pooled connection is invalidated.
probe verify-active "$SESSION_TWO" "$TOKEN_TWO" || probe verify-active "$SESSION_TWO" "$TOKEN_TWO"

echo "== Fault 5: docker restart Redis =="
docker restart "$REDIS_CONTAINER" >/dev/null
sleep 2
# A restart of the same Valkey container must preserve its on-disk snapshot
# and therefore the server-side login session.  Browser/DB state is checked
# independently so an auth-cache result can never mask a ghost session.
probe token-state "$TOKEN_TWO" present
probe verify-active "$SESSION_TWO" "$TOKEN_TWO"

echo "== Fault 6: stop ClamAV (fail closed) =="
docker cp "$SCRIPT_DIR/security-release-review.py" "$BACKEND_CONTAINER:/tmp/security-release-review.py"
docker stop "$CLAMAV_CONTAINER" >/dev/null
sleep 2
SCAN_RESULT=$(MSYS_NO_PATHCONV=1 docker exec -e PYTHONPATH=/app "$BACKEND_CONTAINER" \
    python /tmp/security-release-review.py outage)
printf '%s' "$SCAN_RESULT" | grep -q '"scanner_status": "ERROR"'
printf '%s' "$SCAN_RESULT" | grep -q '"status": "QUARANTINED"'
docker start "$CLAMAV_CONTAINER" >/dev/null
sleep 3

echo "== Fault 7: manually leave an orphan Browser container =="
ORPHAN_RESULT=$(probe create-orphan)
ORPHAN_ID=$(printf '%s' "$ORPHAN_RESULT" | json_field session_id)
probe reconcile-orphan "$ORPHAN_ID"

echo "== Fault 8: kill session during STARTING =="
rm -f "$START_LOG"
(probe startup-kill >"$START_LOG" 2>&1) &
START_PID=$!
i=0
until grep -q '^STARTING_SESSION_ID=' "$START_LOG" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -ge 100 ]; then
        cat "$START_LOG" >&2 || true
        echo "startup probe never exposed its deterministic kill window" >&2
        kill "$START_PID" >/dev/null 2>&1 || true
        exit 1
    fi
    sleep 0.1
done
STARTING_ID=$(sed -n 's/^STARTING_SESSION_ID=//p' "$START_LOG" | tail -n 1)
docker kill "openrbi-session-$STARTING_ID" >/dev/null
wait "$START_PID"
cat "$START_LOG"
if docker inspect "openrbi-session-$STARTING_ID" >/dev/null 2>&1; then
    echo "startup-killed browser container still exists" >&2
    exit 1
fi

echo "== Faults 9/10: Worker Drain and Maintenance =="
probe node-modes "$SESSION_TWO"

echo "== Fault 11: interrupt Session Agent network =="
docker network disconnect "$CONTROL_PLANE_NETWORK" "$SESSION_AGENT_CONTAINER"
probe agent-unavailable
# Recreate instead of guessing a dynamic control-plane address on reconnect.
docker compose up -d --force-recreate session-agent >/dev/null
wait_agent
probe verify-active "$SESSION_TWO" "$TOKEN_TWO"

trap - EXIT INT TERM
restore_dependencies
echo "PASS: all destructive fault-injection acceptance scenarios recovered without ghost state or lost capacity"
