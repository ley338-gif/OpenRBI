#!/bin/sh
# Segmented-deployment credential scoping (docs/adr/0025-segmented-
# credential-scoping.md): proves the two new boundaries are real at the
# engine level, not just documented — a genuine Postgres permission-denied
# error for the openrbi_user role against admin-only surface, and a
# genuine 401 from the Session Agent for a user-scoped token calling an
# admin-scoped route.
#
# Unlike scripts/run-security-tests.sh, this is NOT wired into the default
# CI job: it requires a stack actually brought up with
# docker-compose.segmented.yml layered on top of docker-compose.yml, the
# Postgres roles already provisioned (scripts/provision-segmented-db-roles.sh,
# run once after migrations), and a .env with the Segmented-only
# credential-scoping variables set (see .env.example) — none of which the
# default single-stack CI run configures. Run this by hand (or from a
# dedicated CI job, mirroring how ldap-integration-tests gets its own
# throwaway stack) after bringing up a Segmented+scoped-credentials stack:
#
#   docker compose -f docker-compose.yml -f docker-compose.segmented.yml up -d --build
#   docker exec $(docker compose ps -q backend) alembic upgrade head
#   ./scripts/provision-segmented-db-roles.sh
#   docker compose -f docker-compose.yml -f docker-compose.segmented.yml up -d backend-user backend-admin
#   ./scripts/test-segmented-credential-scoping.sh
set -eu

POSTGRES_CONTAINER="${OPENRBI_POSTGRES_CONTAINER:-openrbi-postgres-1}"
SESSION_AGENT_CONTAINER="${OPENRBI_SESSION_AGENT_CONTAINER:-openrbi-session-agent-1}"
POSTGRES_DB_NAME="${POSTGRES_DB:-openrbi}"

pass=0
fail=0

require_env() {
    var_name="$1"
    eval "value=\${$var_name:-}"
    if [ -z "$value" ]; then
        echo "SKIP: $var_name is not set — this stack hasn't opted into Segmented credential scoping (see .env.example)."
        echo "Nothing to test; exiting 0 rather than failing a feature that was never configured."
        exit 0
    fi
}

require_env OPENRBI_DB_USER_ROLE_PASSWORD
require_env OPENRBI_SESSION_AGENT_API_TOKEN_USER
require_env OPENRBI_SESSION_AGENT_API_TOKEN_ADMIN

echo "== Postgres: openrbi_user role is denied admin-only surface =="

# PGPASSWORD via env, not a CLI arg, so it never shows up in `docker exec`'s
# own process listing on the host.
denied() {
    desc="$1"; sql="$2"
    if docker exec -e PGPASSWORD="$OPENRBI_DB_USER_ROLE_PASSWORD" "$POSTGRES_CONTAINER" \
        psql -v ON_ERROR_STOP=1 -U openrbi_user -d "$POSTGRES_DB_NAME" -c "$sql" >/tmp/openrbi-scoping-test.log 2>&1; then
        echo "FAIL: $desc (statement succeeded — expected a permission-denied error)"
        fail=$((fail + 1))
    elif grep -qi "permission denied" /tmp/openrbi-scoping-test.log; then
        echo "PASS: $desc (permission denied, as expected)"
        pass=$((pass + 1))
    else
        echo "FAIL: $desc (failed, but not with a permission-denied error)"
        cat /tmp/openrbi-scoping-test.log
        fail=$((fail + 1))
    fi
}

denied "openrbi_user cannot read ldap_configs" "SELECT * FROM ldap_configs;"
denied "openrbi_user cannot read policies" "SELECT * FROM policies;"
denied "openrbi_user cannot self-promote via role_id" \
    "UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'ADMIN') WHERE username = 'nonexistent-probe-user';"
denied "openrbi_user cannot insert a new users row" \
    "INSERT INTO users (id, username, role_id, is_active, mfa_enabled) SELECT gen_random_uuid(), 'openrbi-scoping-probe', id, true, false FROM roles WHERE name = 'USER';"
rm -f /tmp/openrbi-scoping-test.log

echo
echo "== Session Agent: a user-scoped token is denied admin-scoped routes =="

agent_status() {
    method="$1"; path="$2"; token="$3"
    docker exec "$SESSION_AGENT_CONTAINER" python3 -c "
import urllib.request, urllib.error
req = urllib.request.Request('http://localhost:8100$path', method='$method', headers={'X-Openrbi-Agent-Token': '$token'})
try:
    with urllib.request.urlopen(req, timeout=5) as r:
        print(r.status)
except urllib.error.HTTPError as e:
    print(e.code)
"
}

fake_session_id="openrbi-scoping-probe-$$"

status=$(agent_status GET "/v1/sandboxes" "$OPENRBI_SESSION_AGENT_API_TOKEN_USER")
if [ "$status" = "401" ]; then
    echo "PASS: user-scoped token denied GET /v1/sandboxes (list-all is admin-only) (got $status)"
    pass=$((pass + 1))
else
    echo "FAIL: user-scoped token was NOT denied GET /v1/sandboxes (expected 401, got $status)"
    fail=$((fail + 1))
fi

status=$(agent_status POST "/v1/sandboxes/$fake_session_id/isolate" "$OPENRBI_SESSION_AGENT_API_TOKEN_USER")
if [ "$status" = "401" ]; then
    echo "PASS: user-scoped token denied POST .../isolate (got $status)"
    pass=$((pass + 1))
else
    echo "FAIL: user-scoped token was NOT denied POST .../isolate (expected 401, got $status)"
    fail=$((fail + 1))
fi

# The admin token must be *accepted* for the same route — a 502 (the
# provider genuinely failing to isolate a nonexistent sandbox) proves the
# auth/scope check passed and execution moved on to the real operation;
# only 401 would mean the scope check itself rejected it.
status=$(agent_status POST "/v1/sandboxes/$fake_session_id/isolate" "$OPENRBI_SESSION_AGENT_API_TOKEN_ADMIN")
if [ "$status" != "401" ]; then
    echo "PASS: admin-scoped token accepted for POST .../isolate (got $status, not 401)"
    pass=$((pass + 1))
else
    echo "FAIL: admin-scoped token was incorrectly denied POST .../isolate (got 401)"
    fail=$((fail + 1))
fi

# A user-scoped token must still work for its own genuinely user-facing
# routes — proves this is real scoping, not an accidental blanket deny.
status=$(agent_status GET "/v1/nodes/self" "$OPENRBI_SESSION_AGENT_API_TOKEN_USER")
if [ "$status" != "401" ]; then
    echo "PASS: user-scoped token accepted for GET /v1/nodes/self (select_node()'s own dependency) (got $status)"
    pass=$((pass + 1))
else
    echo "FAIL: user-scoped token was incorrectly denied GET /v1/nodes/self (got 401) — this would break real session creation"
    fail=$((fail + 1))
fi

echo
echo "== Summary: $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
