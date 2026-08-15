#!/bin/sh
# Phase 21 (Integration-/Securitytests): the subset of docs/development.md's
# checklist that cannot run inside the pytest suite (backend/tests/), because
# it needs either the Docker socket (which the backend deliberately never
# has, ADR 0005) or the ability to stop/start other containers. Run this
# against a live `docker compose up` stack, from the host.
#
# Covers:
#   1. Sandbox network egress: public internet reachable, RFC1918/loopback/
#      link-local/control-plane blocked (docs/security-model.md).
#   2. An admin Isolate actually leaves the sandbox container with zero
#      Docker networks attached — the real DENY-ALL primitive, not just a
#      database flag.
#   3. Fail-closed: a scanner outage blocks an otherwise-auto-releasable
#      file rather than releasing it (ADR 0008), verified by actually
#      stopping the ClamAV container.
#   4. Sandbox-to-sandbox isolation: a real sandbox's own VNC port is
#      unreachable from anything else on browser-plane, including another
#      session (Roadmap Phase A / A3 — the threat-model.md "malicious
#      normal user"/"compromised browser container" rows assume this
#      holds, but it was previously only ever checked once by hand during
#      Phase 9, never by an automated test).
#   5. DNS-rebinding: a hostname that resolves to a blocked address is
#      still blocked, proving the egress rule is enforced against the
#      resolved IP, not the hostname string that requested it (Roadmap
#      Phase A / A3).
#
# Does not tear down/restart the stack on failure beyond its own test
# artifacts; a failed assertion below indicates a real regression, not a
# flaky test — investigate rather than re-run.
set -eu

BACKEND_CONTAINER="${OPENRBI_BACKEND_CONTAINER:-openrbi-backend-1}"
SESSION_AGENT_CONTAINER="${OPENRBI_SESSION_AGENT_CONTAINER:-openrbi-session-agent-1}"
POSTGRES_CONTAINER="${OPENRBI_POSTGRES_CONTAINER:-openrbi-postgres-1}"
REDIS_CONTAINER="${OPENRBI_REDIS_CONTAINER:-openrbi-redis-1}"
CLAMAV_CONTAINER="${OPENRBI_CLAMAV_CONTAINER:-openrbi-clamav-1}"
BROWSER_PLANE_NETWORK="${OPENRBI_BROWSER_PLANE_NETWORK:-openrbi_browser-plane}"
CONTROL_PLANE_NETWORK="${OPENRBI_CONTROL_PLANE_NETWORK:-openrbi_control-plane}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

pass=0
fail=0

check() {
    # check <description> <expected 0|nonzero> <command...>
    desc="$1"; expect_zero="$2"; shift 2
    if "$@" >/tmp/openrbi-check-out 2>&1; then rc=0; else rc=$?; fi
    if { [ "$expect_zero" = "0" ] && [ "$rc" -eq 0 ]; } || { [ "$expect_zero" != "0" ] && [ "$rc" -ne 0 ]; }; then
        echo "PASS: $desc"
        pass=$((pass + 1))
    else
        echo "FAIL: $desc (exit=$rc)"
        cat /tmp/openrbi-check-out
        fail=$((fail + 1))
    fi
}

echo "== 1. Sandbox network isolation =="

check "browser-plane reaches the public internet" 0 \
    docker run --rm --network "$BROWSER_PLANE_NETWORK" curlimages/curl:8.10.1 -sf --max-time 5 -o /dev/null http://example.com

POSTGRES_IP=$(docker inspect "$POSTGRES_CONTAINER" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
check "browser-plane cannot reach Postgres's real container IP" 1 \
    docker run --rm --network "$BROWSER_PLANE_NETWORK" curlimages/curl:8.10.1 -sf --max-time 3 -o /dev/null "http://$POSTGRES_IP:5432"

check "browser-plane cannot reach the cloud metadata address" 1 \
    docker run --rm --network "$BROWSER_PLANE_NETWORK" curlimages/curl:8.10.1 -sf --max-time 3 -o /dev/null http://169.254.169.254

check "browser-plane cannot reach an arbitrary RFC1918 address" 1 \
    docker run --rm --network "$BROWSER_PLANE_NETWORK" curlimages/curl:8.10.1 -sf --max-time 3 -o /dev/null http://10.0.0.1

check "browser-plane loopback remains container-local and cannot reach the host" 1 \
    docker run --rm --network "$BROWSER_PLANE_NETWORK" curlimages/curl:8.10.1 -sf --max-time 3 -o /dev/null http://127.0.0.1:8080

control_ip() {
    docker inspect "$1" --format "{{with index .NetworkSettings.Networks \"$CONTROL_PLANE_NETWORK\"}}{{.IPAddress}}{{end}}"
}

BACKEND_CONTROL_IP=$(control_ip "$BACKEND_CONTAINER")
AGENT_CONTROL_IP=$(control_ip "$SESSION_AGENT_CONTAINER")
REDIS_CONTROL_IP=$(control_ip "$REDIS_CONTAINER")
CLAMAV_CONTROL_IP=$(control_ip "$CLAMAV_CONTAINER")
for target in \
    "$BACKEND_CONTROL_IP:8000:backend/admin API" \
    "$AGENT_CONTROL_IP:8100:Session Agent" \
    "$REDIS_CONTROL_IP:6379:Redis" \
    "$CLAMAV_CONTROL_IP:3310:ClamAV"; do
    address=${target%%:*}
    rest=${target#*:}
    port=${rest%%:*}
    label=${rest#*:}
    check "browser-plane cannot reach $label" 1 \
        docker run --rm --network "$BROWSER_PLANE_NETWORK" curlimages/curl:8.10.1 \
            -s --connect-timeout 2 --max-time 3 "telnet://$address:$port"
done

if [ "$(docker network inspect "$BROWSER_PLANE_NETWORK" --format '{{.EnableIPv6}}')" = "false" ]; then
    echo "PASS: browser-plane has IPv6 disabled, so no IPv6 egress bypass exists"
    pass=$((pass + 1))
else
    echo "FAIL: browser-plane unexpectedly has IPv6 enabled"
    fail=$((fail + 1))
fi

echo "== 2. Isolate actually removes all Docker networks from the sandbox =="

TEST_SESSION_ID=$(docker exec "$BACKEND_CONTAINER" python -c "import uuid; print(uuid.uuid4())")
docker exec "$SESSION_AGENT_CONTAINER" python -c "
import asyncio
from app.providers.factory import get_provider
from app.providers.base import SandboxConfig

async def main():
    provider = get_provider()
    config = SandboxConfig(
        image='openrbi-browser:latest', cpu_limit=1.0, ram_limit_mb=512,
        pid_limit=128, disk_limit_mb=512, network_name='openrbi_browser-plane',
        screen_width=1280, screen_height=800,
    )
    await provider.create_session('$TEST_SESSION_ID', config)
    await provider.start_session('$TEST_SESSION_ID')

asyncio.run(main())
"
TEST_CONTAINER_NAME="openrbi-session-$TEST_SESSION_ID"

SANDBOX_USER=$(docker inspect "$TEST_CONTAINER_NAME" --format '{{.Config.User}}')
SANDBOX_MOUNTS=$(docker inspect "$TEST_CONTAINER_NAME" --format '{{range .Mounts}}{{.Source}}:{{.Destination}} {{end}}')
SANDBOX_CAPS=$(docker inspect "$TEST_CONTAINER_NAME" --format '{{json .HostConfig.CapDrop}}')
SANDBOX_SECURITY=$(docker inspect "$TEST_CONTAINER_NAME" --format '{{json .HostConfig.SecurityOpt}}')
SANDBOX_PRIVILEGED=$(docker inspect "$TEST_CONTAINER_NAME" --format '{{.HostConfig.Privileged}}')
SANDBOX_READONLY=$(docker inspect "$TEST_CONTAINER_NAME" --format '{{.HostConfig.ReadonlyRootfs}}')

if [ -n "$SANDBOX_USER" ] && [ "$SANDBOX_USER" != "0" ] && [ "$SANDBOX_USER" != "root" ]; then
    echo "PASS: sandbox runtime user is non-root ($SANDBOX_USER)"
    pass=$((pass + 1))
else
    echo "FAIL: sandbox runtime user is root or unset ($SANDBOX_USER)"
    fail=$((fail + 1))
fi
case "$SANDBOX_MOUNTS" in
    *docker.sock*|*quarantine*)
        echo "FAIL: sandbox exposes Docker socket or quarantine storage: $SANDBOX_MOUNTS"
        fail=$((fail + 1))
        ;;
    *)
        echo "PASS: sandbox exposes neither Docker socket nor quarantine storage"
        pass=$((pass + 1))
        ;;
esac
if [ "$SANDBOX_PRIVILEGED" = "false" ] && [ "$SANDBOX_READONLY" = "true" ] \
    && [ "$SANDBOX_CAPS" = '["ALL"]' ]; then
    echo "PASS: sandbox is unprivileged, read-only, and drops all capabilities"
    pass=$((pass + 1))
else
    echo "FAIL: sandbox hardening mismatch (privileged=$SANDBOX_PRIVILEGED readonly=$SANDBOX_READONLY caps=$SANDBOX_CAPS)"
    fail=$((fail + 1))
fi
case "$SANDBOX_SECURITY" in
    *no-new-privileges*)
        echo "PASS: sandbox enforces no-new-privileges"
        pass=$((pass + 1))
        ;;
    *)
        echo "FAIL: sandbox lacks no-new-privileges: $SANDBOX_SECURITY"
        fail=$((fail + 1))
        ;;
esac

docker exec "$SESSION_AGENT_CONTAINER" python -c "
import asyncio
from app.providers.factory import get_provider

asyncio.run(get_provider().isolate_session('$TEST_SESSION_ID'))
"
NETWORKS=$(docker inspect "$TEST_CONTAINER_NAME" --format '{{len .NetworkSettings.Networks}}')
if [ "$NETWORKS" = "0" ]; then
    echo "PASS: isolated sandbox has zero attached networks"
    pass=$((pass + 1))
else
    echo "FAIL: isolated sandbox still has $NETWORKS network(s) attached"
    fail=$((fail + 1))
fi
docker rm -f "$TEST_CONTAINER_NAME" >/dev/null 2>&1 || true

echo "== 3. Fail-closed: scanner outage blocks release =="

docker cp "$SCRIPT_DIR/security-release-review.py" "$BACKEND_CONTAINER:/tmp/security-release-review.py"
CLEAN_RESULT=$(docker exec -e PYTHONPATH=/app "$BACKEND_CONTAINER" \
    python /tmp/security-release-review.py clean)
EICAR_RESULT=$(docker exec -e PYTHONPATH=/app "$BACKEND_CONTAINER" \
    python /tmp/security-release-review.py eicar)
echo "$CLEAN_RESULT" | grep -q '"scanner_status": "CLEAN"'
echo "$CLEAN_RESULT" | grep -q '"status": "RELEASED"'
echo "$EICAR_RESULT" | grep -q '"scanner_status": "INFECTED"'
echo "$EICAR_RESULT" | grep -q '"status": "QUARANTINED"'
echo "PASS: benign file is released only after a real clean scan with SHA-256 evidence"
pass=$((pass + 1))
echo "PASS: real EICAR detection quarantines the file and creates malware evidence"
pass=$((pass + 1))

docker stop "$CLAMAV_CONTAINER" >/dev/null
# Give clamd's own TCP listener time to actually go away rather than racing
# the stop.
sleep 2

if SCAN_RESULT=$(docker exec -e PYTHONPATH=/app "$BACKEND_CONTAINER" \
    python /tmp/security-release-review.py outage); then
    SCAN_RC=0
else
    SCAN_RC=$?
fi
docker start "$CLAMAV_CONTAINER" >/dev/null
sleep 3
if [ "$SCAN_RC" -eq 0 ] \
    && echo "$SCAN_RESULT" | grep -q '"scanner_status": "ERROR"' \
    && echo "$SCAN_RESULT" | grep -q '"status": "QUARANTINED"'; then
    echo "PASS: scanner outage keeps AUTO_RELEASE content quarantined and audited"
    pass=$((pass + 1))
else
    echo "FAIL: scanner-outage pipeline probe failed (exit=$SCAN_RC): $SCAN_RESULT"
    fail=$((fail + 1))
fi

echo "== 4. Sandbox-to-sandbox isolation =="

create_test_sandbox() {
    # Prints the new session id on stdout. Mirrors section 2's own
    # create+start sequence exactly, just without the isolate call.
    sid=$(docker exec "$BACKEND_CONTAINER" python -c "import uuid; print(uuid.uuid4())")
    docker exec "$SESSION_AGENT_CONTAINER" python -c "
import asyncio
from app.providers.factory import get_provider
from app.providers.base import SandboxConfig

async def main():
    provider = get_provider()
    config = SandboxConfig(
        image='openrbi-browser:latest', cpu_limit=1.0, ram_limit_mb=512,
        pid_limit=128, disk_limit_mb=512, network_name='openrbi_browser-plane',
        screen_width=1280, screen_height=800,
    )
    await provider.create_session('$sid', config)
    await provider.start_session('$sid')

asyncio.run(main())
" >/dev/null
    echo "$sid"
}

SANDBOX_ID=$(create_test_sandbox)
SANDBOX_CONTAINER="openrbi-session-$SANDBOX_ID"
# x11vnc's RFB port (docker/browser/entrypoint.sh) — the one port a real
# session's own display relay would connect to, so it's the meaningful
# target here, not an arbitrary port pick.
SANDBOX_IP=$(docker inspect "$SANDBOX_CONTAINER" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')

# The browser image itself has no curl/wget (docker/browser/Dockerfile only
# installs firefox-esr/xvfb/x11vnc/dbus-x11 — nothing that could exec a
# probe from inside a real sandbox container). A throwaway curl container
# attached to the same browser-plane network is an equally valid probe:
# the DOCKER-USER iptables rules (scripts/setup-network-isolation.sh) key
# on source/destination *IP*, not container identity, so this exercises
# the identical rule a real second sandbox's traffic would hit.
check "another browser-plane member cannot reach this sandbox's VNC port" 1 \
    docker run --rm --network "$BROWSER_PLANE_NETWORK" curlimages/curl:8.10.1 -sf --max-time 3 -o /dev/null "http://$SANDBOX_IP:5900"

docker rm -f "$SANDBOX_CONTAINER" >/dev/null 2>&1 || true

echo "== 5. DNS-rebinding: an attacker-controlled hostname resolving to a blocked address is still blocked =="

# --resolve fakes the DNS answer entirely client-side — no real rebinding
# attack infrastructure needed to prove the point. If the egress rule only
# matched on the hostname string (or trusted the first DNS answer without
# re-checking the address actually dialed), this would incorrectly succeed;
# since the block is iptables rules against the resolved IP itself
# (scripts/setup-network-isolation.sh), it doesn't matter what hostname
# asked for that address.
check "a rebound hostname pointing at Postgres's real IP is still blocked" 1 \
    docker run --rm --network "$BROWSER_PLANE_NETWORK" curlimages/curl:8.10.1 \
        --resolve "totally-legit-cdn.example.com:80:$POSTGRES_IP" \
        -sf --max-time 3 -o /dev/null "http://totally-legit-cdn.example.com:80"

echo
echo "== Summary: $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
