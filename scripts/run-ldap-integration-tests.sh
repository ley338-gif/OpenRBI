#!/bin/sh
# Roadmap Phase B / B1.4-B1.6 — HTTP-level tests against the real
# /auth/login endpoint with LDAP genuinely enabled (backend/tests/
# integration/test_ldap_login_flow.py), as opposed to
# scripts/run-ldap-tests.sh, which exercises LdapAuthProvider directly
# without ever restarting the backend or touching /auth/login.
#
# Unlike every other test runner in this project, this one has to
# actually start a backend process with different environment
# (OPENRBI_LDAP_* pointed at a throwaway server) for the real /auth/login
# endpoint to see it at all — the running uvicorn process reads
# Settings() once at import time, so there is no way to flip this per-
# request. A separate throwaway backend container reuses the already-built
# Compose image and network. This leaves the application backend and .env
# untouched and avoids a resource-heavy image rebuild/container recreate.
set -eu

BACKEND_CONTAINER="${OPENRBI_LDAP_TEST_BACKEND_CONTAINER:-openrbi-test-backend-ldap}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
LDAP_CONTAINER=openrbi-test-ldap-integration
LDAP_ADMIN_PASSWORD="test-admin-password-throwaway"
TEST_USER_USERNAME="pytest_ldapadmin"
TEST_USER_PASSWORD="PytestLdapAdmin2026!"

cleanup() {
    echo "[ldap-integration-tests] removing throwaway containers..."
    docker rm -f "$BACKEND_CONTAINER" >/dev/null 2>&1 || true
    docker rm -f "$LDAP_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[ldap-integration-tests] starting throwaway LDAPS server..."
docker rm -f "$LDAP_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$LDAP_CONTAINER" \
    --network openrbi_control-plane \
    -e LDAP_ORGANISATION="OpenRBI Test" \
    -e LDAP_DOMAIN="example.org" \
    -e LDAP_ADMIN_PASSWORD="$LDAP_ADMIN_PASSWORD" \
    -e LDAP_TLS=true \
    -e LDAP_TLS_VERIFY_CLIENT=never \
    osixia/openldap:1.5.0 >/dev/null

for i in $(seq 1 30); do
    if docker exec "$LDAP_CONTAINER" ldapsearch -x -H ldap://localhost -b "dc=example,dc=org" -D "cn=admin,dc=example,dc=org" -w "$LDAP_ADMIN_PASSWORD" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# memberOf is not maintained automatically by plain OpenLDAP without this
# overlay — real AD computes it natively, but this throwaway test server
# needs it enabled explicitly, or every user's group membership would be
# invisible to LdapAuthProvider's search and every login would resolve to
# the default USER role regardless of actual group membership (a real gap
# found and fixed while first verifying B1.3 manually, not assumed).
docker exec -i "$LDAP_CONTAINER" ldapmodify -Y EXTERNAL -H ldapi:/// >/dev/null 2>&1 <<'EOF' || true
dn: cn=module{0},cn=config
changetype: modify
add: olcModuleLoad
olcModuleLoad: memberof
EOF
docker exec -i "$LDAP_CONTAINER" ldapmodify -Y EXTERNAL -H ldapi:/// <<'EOF'
dn: olcOverlay=memberof,olcDatabase={1}mdb,cn=config
changetype: add
objectClass: olcOverlayConfig
objectClass: olcMemberOf
olcOverlay: memberof
EOF

docker exec -i "$LDAP_CONTAINER" ldapadd -x -H ldap://localhost -D "cn=admin,dc=example,dc=org" -w "$LDAP_ADMIN_PASSWORD" <<EOF
dn: ou=people,dc=example,dc=org
objectClass: organizationalUnit
ou: people

dn: ou=groups,dc=example,dc=org
objectClass: organizationalUnit
ou: groups

dn: uid=$TEST_USER_USERNAME,ou=people,dc=example,dc=org
objectClass: inetOrgPerson
objectClass: posixAccount
objectClass: shadowAccount
uid: $TEST_USER_USERNAME
cn: Pytest LDAP Admin
sn: Admin
givenName: Pytest
mail: $TEST_USER_USERNAME@example.org
uidNumber: 20000
gidNumber: 20000
homeDirectory: /home/$TEST_USER_USERNAME
userPassword: $TEST_USER_PASSWORD

dn: cn=openrbi-admins,ou=groups,dc=example,dc=org
objectClass: groupOfNames
cn: openrbi-admins
member: uid=$TEST_USER_USERNAME,ou=people,dc=example,dc=org
EOF

echo "[ldap-integration-tests] starting throwaway LDAP-enabled backend..."
BACKEND_IMAGE="$(cd "$REPO_ROOT" && docker compose images -q backend)"
if [ -z "$BACKEND_IMAGE" ]; then
    echo "[ldap-integration-tests] backend image is missing; start/build the Compose stack first" >&2
    exit 1
fi
docker rm -f "$BACKEND_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$BACKEND_CONTAINER" \
    --network openrbi_control-plane \
    --env-file "$REPO_ROOT/.env" \
    -e OPENRBI_LDAP_ENABLED=true \
    -e "OPENRBI_LDAP_SERVER_URI=ldaps://$LDAP_CONTAINER:636" \
    -e OPENRBI_LDAP_USE_STARTTLS=true \
    -e OPENRBI_LDAP_BIND_DN=cn=admin,dc=example,dc=org \
    -e "OPENRBI_LDAP_BIND_PASSWORD=$LDAP_ADMIN_PASSWORD" \
    -e OPENRBI_LDAP_BASE_DN=dc=example,dc=org \
    -e 'OPENRBI_LDAP_USER_SEARCH_FILTER=(uid={username})' \
    -e OPENRBI_LDAP_GROUP_ATTRIBUTE=memberOf \
    -e 'OPENRBI_LDAP_GROUP_ROLE_MAPPING={"cn=openrbi-admins,ou=groups,dc=example,dc=org":"ADMIN"}' \
    -e LDAPTLS_REQCERT=never \
    "$BACKEND_IMAGE" >/dev/null

echo "[ldap-integration-tests] waiting for backend to come back up..."
for i in $(seq 1 30); do
    if docker exec "$BACKEND_CONTAINER" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[ldap-integration-tests] throwaway backend did not become healthy within 30 seconds" >&2
        docker logs "$BACKEND_CONTAINER" >&2 || true
        exit 1
    fi
    sleep 1
done

docker exec -u root "$BACKEND_CONTAINER" pip install --quiet ".[dev]"
# test_ldap_login_flow.py imports `from tests.conftest import ...`, same as
# every other integration test file — it must live inside the real tests/
# package structure, not be copied as a standalone file, or that import
# fails with "No module named 'tests'". Copy the whole tree, same as
# scripts/run-integration-tests.sh does.
MSYS_NO_PATHCONV=1 docker exec -u root "$BACKEND_CONTAINER" rm -rf /app/tests
docker cp "$SCRIPT_DIR/../backend/tests" "$BACKEND_CONTAINER:/app/tests"
docker cp "$SCRIPT_DIR/../backend/pyproject.toml" "$BACKEND_CONTAINER:/app/pyproject.toml"

echo "[ldap-integration-tests] running MFA/lockout/local-regression tests..."
MSYS_NO_PATHCONV=1 docker exec \
    -e OPENRBI_LDAP_TEST_ADMIN_USERNAME="$TEST_USER_USERNAME" \
    -e OPENRBI_LDAP_TEST_ADMIN_PASSWORD="$TEST_USER_PASSWORD" \
    "$BACKEND_CONTAINER" pytest -v -p no:cacheprovider tests/integration/test_ldap_login_flow.py \
    -k "not test_ldap_server_unreachable_denies_login_no_fallback"

# Roadmap B1.8.5: test_admin_ldap.py drives app/api/admin_ldap.py over real
# HTTP against this same now-running backend — unlike scripts/
# run-ldap-tests.sh (which talks to LdapAuthProvider in-process, inside the
# pytest process itself), the admin API's TLS handshake happens inside the
# uvicorn process, so it needs the backend container's own
# LDAPTLS_REQCERT=never (set on the throwaway backend above) to trust this
# self-signed cert — that's exactly why this file only runs here, not from
# run-ldap-tests.sh. OPENRBI_LDAP_SERVER_URI/BIND_DN/BASE_DN/etc. are
# are already present in this exec's environment because the throwaway
# backend was started with --env-file plus explicit LDAP overrides, which
# is what the test file's own request payloads are built from.
echo "[ldap-integration-tests] running admin LDAP configuration API tests..."
MSYS_NO_PATHCONV=1 docker exec \
    -e OPENRBI_LDAP_TEST_ADMIN_USERNAME="$TEST_USER_USERNAME" \
    "$BACKEND_CONTAINER" pytest -v -p no:cacheprovider tests/integration/test_admin_ldap.py

echo "[ldap-integration-tests] stopping LDAP server to test the unreachable case..."
docker stop "$LDAP_CONTAINER" >/dev/null
sleep 2

MSYS_NO_PATHCONV=1 docker exec \
    -e OPENRBI_LDAP_TEST_ADMIN_USERNAME="$TEST_USER_USERNAME" \
    -e OPENRBI_LDAP_TEST_ADMIN_PASSWORD="$TEST_USER_PASSWORD" \
    "$BACKEND_CONTAINER" pytest -v -p no:cacheprovider tests/integration/test_ldap_login_flow.py \
    -k "test_ldap_server_unreachable_denies_login_no_fallback"

docker start "$LDAP_CONTAINER" >/dev/null
echo "[ldap-integration-tests] all tests passed"
