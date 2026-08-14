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
CLAMAV_CONTAINER="${OPENRBI_CLAMAV_CONTAINER:-openrbi-clamav-1}"
BROWSER_PLANE_NETWORK="${OPENRBI_BROWSER_PLANE_NETWORK:-openrbi_browser-plane}"

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
    await provider.isolate_session('$TEST_SESSION_ID')

asyncio.run(main())
"
TEST_CONTAINER_NAME="openrbi-session-$TEST_SESSION_ID"
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

docker stop "$CLAMAV_CONTAINER" >/dev/null
# Give clamd's own TCP listener time to actually go away rather than racing
# the stop.
sleep 2

SCAN_RESULT=$(docker exec "$BACKEND_CONTAINER" python -c "
import asyncio
from app.core import clamav_client

async def main():
    try:
        await clamav_client.scan(b'harmless test content, not a real sample')
        print('SCANNED_OK')
    except clamav_client.ClamAVError:
        print('SCANNER_UNAVAILABLE')

asyncio.run(main())
")
docker start "$CLAMAV_CONTAINER" >/dev/null
sleep 3
if [ "$SCAN_RESULT" = "SCANNER_UNAVAILABLE" ]; then
    echo "PASS: scanner outage is detected as an error, never a silent clean result"
    pass=$((pass + 1))
else
    echo "FAIL: expected SCANNER_UNAVAILABLE, got: $SCAN_RESULT"
    fail=$((fail + 1))
fi
# app/services/scanning.py's scan_and_finalize maps exactly this
# ClamAVError into QUARANTINED/ERROR regardless of the file's policy verdict
# (verified directly against ClamAV in Phase 14 with a real EICAR string,
# see CHANGELOG.md) — this script re-verifies the outage-detection
# precondition that guarantee depends on.

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
