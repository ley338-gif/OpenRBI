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

NODE2_PROJECT="${OPENRBI_NODE2_PROJECT:-openrbi-node2-fault-test}"
NODE2_OVERRIDE="/tmp/openrbi-node2-fault-test.override.yml"

restore_dependencies() {
    docker start "$POSTGRES_CONTAINER" "$REDIS_CONTAINER" "$CLAMAV_CONTAINER" >/dev/null 2>&1 || true
    docker start "$SESSION_AGENT_CONTAINER" >/dev/null 2>&1 || true
    if ! docker inspect "$SESSION_AGENT_CONTAINER" --format \
        "{{with index .NetworkSettings.Networks \"$CONTROL_PLANE_NETWORK\"}}{{.IPAddress}}{{end}}" \
        2>/dev/null | grep -q .; then
        docker compose up -d --force-recreate session-agent >/dev/null 2>&1 || true
    fi
    # Roadmap B2.7 — Fault 12 deliberately leaves node2's own sandbox
    # container behind (an unreachable node's containers are the
    # operator's concern once it's reachable again, per ADR 0024/B2.5's
    # documented behavior — this proves that rather than hiding it), so
    # `docker network rm` below would otherwise fail with "has active
    # endpoints". Remove every container still attached to node2's own
    # browser-plane by network membership, not compose labels (the
    # sandbox itself carries session-agent's own openrbi.managed label,
    # never a compose one).
    docker network inspect "${NODE2_PROJECT}_browser-plane" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null \
        | tr ' ' '\n' | while IFS= read -r name; do
            [ -n "$name" ] || continue
            docker rm -f "$name" >/dev/null 2>&1 || true
        done
    docker compose -p "$NODE2_PROJECT" -f "$SCRIPT_DIR/../docker-compose.node.yml" -f "$NODE2_OVERRIDE" \
        down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -f "$NODE2_OVERRIDE"
    # Roadmap B3.2 — Fault 14's real memory-pressure container, in case
    # an earlier assertion in that fault exited the script before its own
    # cleanup ran.
    docker rm -f openrbi-fault-mem-pressure >/dev/null 2>&1 || true
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

echo "== Fault 12: kill one of N nodes mid-session (Roadmap B2.7) =="

# A real second node, brought up exactly the way an operator would
# (docker-compose.node.yml), self-enrolling with a real single-use
# enrollment token. -p gives it its own project (and therefore its own
# browser-plane) so it can coexist with the primary stack on this same
# CI runner without colliding — see docker-compose.node.yml's own
# comments on OPENRBI_AGENT_SANDBOX_NETWORK_NAME, needed for the same
# reason.
NODE2_HOSTNAME="node2-fault-test-$(date +%s)"
NODE2_TOKEN=$(probe node2-enrollment-token | json_field enrollment_token)
cat > "$NODE2_OVERRIDE" <<EOF
services:
  session-agent:
    environment:
      OPENRBI_AGENT_API_TOKEN: $(openssl rand -hex 32)
      OPENRBI_AGENT_NODE_NAME: ${NODE2_HOSTNAME}
      OPENRBI_AGENT_ENROLLMENT_TOKEN: ${NODE2_TOKEN}
      OPENRBI_AGENT_CONTROL_PLANE_URL: http://backend:8000
      OPENRBI_AGENT_SANDBOX_NETWORK_NAME: ${NODE2_PROJECT}_browser-plane
    networks:
      browser-plane:
        ipv4_address: 172.31.0.2
networks:
  browser-plane:
    ipam:
      config:
        - subnet: 172.31.0.0/24
EOF
docker compose -p "$NODE2_PROJECT" -f docker-compose.node.yml -f "$NODE2_OVERRIDE" up -d >/dev/null
NODE2_CONTAINER="${NODE2_PROJECT}-session-agent-1"
docker network connect "$CONTROL_PLANE_NETWORK" "$NODE2_CONTAINER"

i=0
until docker logs "$NODE2_CONTAINER" 2>&1 | grep -q "node enrollment succeeded"; do
    i=$((i + 1)); [ "$i" -lt 40 ] || { echo "node2 never enrolled" >&2; exit 1; }
    sleep 1
done
probe node2-approve "$NODE2_HOSTNAME" "http://${NODE2_CONTAINER}:8100"

SEED_NODE2=$(probe node2-seed-active "$NODE2_HOSTNAME")
SESSION_NODE2=$(printf '%s' "$SEED_NODE2" | json_field session_id)

# Kill the node outright — not the container it happens to be running on
# a graceful path, an actual process-level failure, the same category of
# fault every earlier scenario in this script injects for the default
# node.
docker kill "$NODE2_CONTAINER" >/dev/null

# Verify all three Definition of Done claims: the killed node's own
# session reaches the B2.5 failure state, the survivor (SESSION_TWO, on
# the default node) is completely unaffected, and select_node() reschedules
# new sessions onto the survivor rather than trying the dead node again.
probe node2-verify-unreachable-session-failed "$SESSION_NODE2"
probe node2-verify-survivor-unaffected "$SESSION_TWO"
probe node2-verify-reschedules-onto-survivor default-node

echo "== Fault 13: interrupt Session Agent network =="
docker network disconnect "$CONTROL_PLANE_NETWORK" "$SESSION_AGENT_CONTAINER"
probe agent-unavailable
# Recreate instead of guessing a dynamic control-plane address on reconnect.
docker compose up -d --force-recreate session-agent >/dev/null
wait_agent
probe verify-active "$SESSION_TWO" "$TOKEN_TWO"

echo "== Fault 14: real host memory pressure drops capacity, with hysteresis (Roadmap B3.2) =="

# A real container that actually commits and touches ~1.2 GB of RAM, not
# a synthetic reading — the default node's own session-agent reads real
# host-wide psutil.virtual_memory(), so this is visible to it exactly the
# way any other real memory consumer on the host would be.
MEM_PRESSURE_CONTAINER="openrbi-fault-mem-pressure"
docker rm -f "$MEM_PRESSURE_CONTAINER" >/dev/null 2>&1 || true
BEFORE_CAPACITY=$(probe capacity-snapshot | json_field capacity)
docker run -d --name "$MEM_PRESSURE_CONTAINER" python:3.11-slim python -c "
import time
data = bytearray(1200 * 1024 * 1024)
for i in range(0, len(data), 4096):
    data[i] = 1
time.sleep(120)
" >/dev/null
sleep 3
DURING_CAPACITY=$(probe capacity-snapshot | json_field capacity)
if [ "$DURING_CAPACITY" -ge "$BEFORE_CAPACITY" ]; then
    echo "capacity did not drop under real memory pressure (before=$BEFORE_CAPACITY during=$DURING_CAPACITY)" >&2
    docker rm -f "$MEM_PRESSURE_CONTAINER" >/dev/null 2>&1 || true
    exit 1
fi

docker rm -f "$MEM_PRESSURE_CONTAINER" >/dev/null

# The drop must not instantly reverse the moment real headroom is back —
# this is the actual hysteresis behavior B3.2 adds, not just B3.1's raw
# computation (already covered by session-agent/tests/test_capacity.py).
# The exact poll count isn't asserted precisely here: node_poller.py
# (backend, real background task) polls the same endpoint independently
# on its own interval and would otherwise advance the recovery streak
# unpredictably relative to this script's own probe calls — the
# meaningful, deterministic claims are "not on the very next poll" and
# "eventually, within a generous bound", not an exact count.
JUST_AFTER_CAPACITY=$(probe capacity-snapshot | json_field capacity)
if [ "$JUST_AFTER_CAPACITY" != "$DURING_CAPACITY" ]; then
    echo "capacity recovered instantly instead of being held (during=$DURING_CAPACITY just_after=$JUST_AFTER_CAPACITY)" >&2
    exit 1
fi

RECOVERED_CAPACITY="$DURING_CAPACITY"
for attempt in $(seq 1 10); do
    RECOVERED_CAPACITY=$(probe capacity-snapshot | json_field capacity)
    [ "$RECOVERED_CAPACITY" -gt "$DURING_CAPACITY" ] && break
    sleep 1
done
if [ "$RECOVERED_CAPACITY" -le "$DURING_CAPACITY" ]; then
    echo "capacity never recovered after sustained real headroom (during=$DURING_CAPACITY recovered=$RECOVERED_CAPACITY)" >&2
    exit 1
fi
echo "PASS: capacity dropped under real memory pressure ($BEFORE_CAPACITY -> $DURING_CAPACITY), was still held on the very next poll after pressure cleared, then recovered ($RECOVERED_CAPACITY)"

trap - EXIT INT TERM
restore_dependencies
echo "PASS: all destructive fault-injection acceptance scenarios recovered without ghost state or lost capacity"
