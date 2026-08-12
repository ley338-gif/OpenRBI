#!/bin/sh
# Productization v0.1.1 (docs/adr/0011-user-admin-listener-separation.md):
# verifies OPENRBI_LISTENER_MODE actually changes which routes exist, not
# just which ones RBAC would 403. Runs from the host because it needs to
# start throwaway sibling backend containers with different env vars —
# the backend container itself has no Docker socket access (ADR 0005), so
# this cannot be a pytest test inside it. Companion to
# scripts/run-security-tests.sh and scripts/run-integration-tests.sh.
#
# Requires the openrbi-backend image already built (docker compose build
# backend) and the control-plane network already up (docker compose up).
set -eu

ENV_FILE="${OPENRBI_ENV_FILE:-.env}"
NETWORK="${OPENRBI_CONTROL_PLANE_NETWORK:-openrbi_control-plane}"
DRIVER_CONTAINER="${OPENRBI_BACKEND_CONTAINER:-openrbi-backend-1}"

pass=0
fail=0

cleanup() {
    docker rm -f openrbi-lt-user openrbi-lt-admin openrbi-lt-invalid >/dev/null 2>&1 || true
}
trap cleanup EXIT

check_status() {
    # check_status <container> <method> <path> <expected-status> <description>
    container="$1"; method="$2"; path="$3"; expected="$4"; desc="$5"
    actual=$(docker exec "$DRIVER_CONTAINER" python -c "
import asyncio, httpx
async def main():
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.request('$method', 'http://$container:8000$path', json={} if '$method' == 'POST' else None)
        print(r.status_code)
asyncio.run(main())
")
    if [ "$actual" = "$expected" ]; then
        echo "PASS: $desc (got $actual)"
        pass=$((pass + 1))
    else
        echo "FAIL: $desc (expected $expected, got $actual)"
        fail=$((fail + 1))
    fi
}

echo "== user mode: user/shared routes exist, admin routes do not exist (404, not 403) =="
docker run --rm -d --name openrbi-lt-user --network "$NETWORK" --env-file "$ENV_FILE" \
    -e OPENRBI_LISTENER_MODE=user openrbi-backend >/dev/null
sleep 2
check_status openrbi-lt-user GET  /health 200 "health (shared) exists"
check_status openrbi-lt-user POST /auth/login 422 "auth login (shared) exists"
check_status openrbi-lt-user POST /mfa/enroll 401 "user MFA enroll exists (401 = auth required, route exists)"
check_status openrbi-lt-user GET  /sessions/me 401 "user sessions exists"
check_status openrbi-lt-user GET  /files/me 401 "user files exists"
check_status openrbi-lt-user GET  /admin/users 404 "admin user mgmt does not exist"
check_status openrbi-lt-user GET  /admin/policies 404 "admin policies does not exist"
check_status openrbi-lt-user GET  /admin/sessions 404 "admin session control does not exist"
check_status openrbi-lt-user GET  /admin/security-events 404 "admin audit does not exist"
check_status openrbi-lt-user GET  /admin/health 404 "admin health does not exist"
check_status openrbi-lt-user POST /mfa/admin/users/00000000-0000-0000-0000-000000000000/reset 404 "admin MFA reset does not exist"

user_has_admin_paths=$(docker exec "$DRIVER_CONTAINER" python -c "
import asyncio, httpx
async def main():
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get('http://openrbi-lt-user:8000/openapi.json')
        paths = r.json()['paths']
        print('yes' if any(p.startswith('/admin') for p in paths) else 'no')
asyncio.run(main())
")
if [ "$user_has_admin_paths" = "no" ]; then
    echo "PASS: user-mode OpenAPI schema contains no /admin paths"
    pass=$((pass + 1))
else
    echo "FAIL: user-mode OpenAPI schema leaks /admin paths"
    fail=$((fail + 1))
fi
docker rm -f openrbi-lt-user >/dev/null 2>&1

echo "== admin mode: shared/admin routes exist, user-only routes do not exist =="
docker run --rm -d --name openrbi-lt-admin --network "$NETWORK" --env-file "$ENV_FILE" \
    -e OPENRBI_LISTENER_MODE=admin openrbi-backend >/dev/null
sleep 2
check_status openrbi-lt-admin GET  /health 200 "health (shared) exists"
check_status openrbi-lt-admin POST /auth/login 422 "auth login (shared) exists"
check_status openrbi-lt-admin POST /mfa/setup/enroll 422 "admin mandatory MFA enrollment exists"
check_status openrbi-lt-admin GET  /admin/users 401 "admin user mgmt exists (401 = auth required, route exists)"
check_status openrbi-lt-admin GET  /admin/policies 401 "admin policies exists"
check_status openrbi-lt-admin GET  /admin/health 401 "admin health exists"
check_status openrbi-lt-admin POST /mfa/admin/users/00000000-0000-0000-0000-000000000000/reset 401 "admin MFA reset exists"
check_status openrbi-lt-admin GET  /sessions/me 404 "user sessions does not exist"
check_status openrbi-lt-admin GET  /files/me 404 "user files does not exist"

admin_has_user_only_paths=$(docker exec "$DRIVER_CONTAINER" python -c "
import asyncio, httpx
async def main():
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get('http://openrbi-lt-admin:8000/openapi.json')
        paths = r.json()['paths']
        leaked = [p for p in paths if p.startswith('/sessions') or p.startswith('/files') or p.startswith('/display')]
        print('yes' if leaked else 'no')
asyncio.run(main())
")
if [ "$admin_has_user_only_paths" = "no" ]; then
    echo "PASS: admin-mode OpenAPI schema contains no user-only paths"
    pass=$((pass + 1))
else
    echo "FAIL: admin-mode OpenAPI schema leaks user-only paths"
    fail=$((fail + 1))
fi
docker rm -f openrbi-lt-admin >/dev/null 2>&1

echo "== both mode: unchanged from prior MVP behavior (spot check) =="
# The already-running compose stack's backend is "both" mode by default;
# reuse it directly rather than starting a third throwaway container.
check_status "$DRIVER_CONTAINER" GET /health 200 "health exists"
check_status "$DRIVER_CONTAINER" GET /admin/users 401 "admin route exists in both mode (401, not 404)"
check_status "$DRIVER_CONTAINER" GET /sessions/me 401 "user route exists in both mode (401, not 404)"

echo "== invalid mode: startup fails fast, does not silently accept =="
set +e
docker run --rm --name openrbi-lt-invalid --network "$NETWORK" --env-file "$ENV_FILE" \
    -e OPENRBI_LISTENER_MODE=banana openrbi-backend >/tmp/openrbi-lt-invalid.log 2>&1
rc=$?
set -e
if [ "$rc" -ne 0 ] && grep -q "listener_mode" /tmp/openrbi-lt-invalid.log; then
    echo "PASS: invalid OPENRBI_LISTENER_MODE fails startup with a clear error"
    pass=$((pass + 1))
else
    echo "FAIL: invalid OPENRBI_LISTENER_MODE did not fail closed as expected (exit=$rc)"
    cat /tmp/openrbi-lt-invalid.log
    fail=$((fail + 1))
fi
rm -f /tmp/openrbi-lt-invalid.log

echo
echo "== Summary: $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
