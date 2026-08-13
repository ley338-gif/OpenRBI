#!/bin/sh
# Roadmap Phase B / B1.6 — runs LdapAuthProvider (backend/app/core/
# auth_providers/ldap.py) against a real, throwaway LDAP server, not a
# mock. Starts osixia/openldap, seeds one test user + one test group via a
# real ldapadd, points the backend's LDAP settings at it, then runs
# backend/tests/integration/test_ldap_auth.py the same way
# scripts/run-integration-tests.sh runs the rest of the suite: copy the
# test file into the already-running backend container (which already has
# python-ldap installed) and invoke pytest there.
#
# This exercises LdapAuthProvider directly, in-process within pytest — it
# never restarts the backend or talks to a running server, so the
# LDAPTLS_REQCERT=never override below only has to apply to *this* pytest
# process. The admin LDAP HTTP API (app/api/admin_ldap.py) is different: it
# runs inside the already-running uvicorn process, which needs its own TLS
# trust for this throwaway self-signed cert — that's covered by
# scripts/run-ldap-integration-tests.sh instead, which actually restarts
# the backend with the right environment (see test_admin_ldap.py there).
#
# Uses OpenLDAP's own native schema (uid=...) rather than Active
# Directory's sAMAccountName — there is no real AD available to test
# against here. OPENRBI_LDAP_USER_SEARCH_FILTER is overridden accordingly
# for this run only; a real deployment against actual AD keeps the
# sAMAccountName default (.env.example).
set -eu

BACKEND_CONTAINER="${OPENRBI_BACKEND_CONTAINER:-openrbi-backend-1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LDAP_CONTAINER=openrbi-test-ldap
LDAP_ADMIN_PASSWORD="test-admin-password-throwaway"
TEST_USER_PASSWORD="TestUserPassword2026!"

cleanup() {
    docker rm -f "$LDAP_CONTAINER" >/dev/null 2>&1 || true
    MSYS_NO_PATHCONV=1 docker exec -u root "$BACKEND_CONTAINER" rm -f /app/test_ldap_auth.py >/dev/null 2>&1 || true
}
trap cleanup EXIT

# LDAP_TLS=true makes the image generate and serve a self-signed cert on
# 636/StartTLS-on-389 at boot — real TLS, not a plaintext bind, so this
# test actually exercises the encrypted path app/config.py's startup
# validation requires. LDAPTLS_REQCERT=never below (applied only to the
# pytest exec's environment, never to the application code itself) is what
# lets the test client trust that self-signed cert without adding any
# cert-verification bypass to LdapAuthProvider — a real deployment against
# a real AD's properly-issued certificate needs no such override.
docker rm -f "$LDAP_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$LDAP_CONTAINER" \
    --network openrbi_control-plane \
    -e LDAP_ORGANISATION="OpenRBI Test" \
    -e LDAP_DOMAIN="example.org" \
    -e LDAP_ADMIN_PASSWORD="$LDAP_ADMIN_PASSWORD" \
    -e LDAP_TLS=true \
    -e LDAP_TLS_VERIFY_CLIENT=never \
    osixia/openldap:1.5.0 >/dev/null

echo "[ldap-tests] waiting for slapd to accept connections..."
for i in $(seq 1 30); do
    if docker exec "$LDAP_CONTAINER" ldapsearch -x -H ldap://localhost -b "dc=example,dc=org" -D "cn=admin,dc=example,dc=org" -w "$LDAP_ADMIN_PASSWORD" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

docker exec -i "$LDAP_CONTAINER" ldapadd -x -H ldap://localhost -D "cn=admin,dc=example,dc=org" -w "$LDAP_ADMIN_PASSWORD" <<EOF
dn: ou=people,dc=example,dc=org
objectClass: organizationalUnit
ou: people

dn: ou=groups,dc=example,dc=org
objectClass: organizationalUnit
ou: groups

dn: uid=testuser,ou=people,dc=example,dc=org
objectClass: inetOrgPerson
objectClass: posixAccount
objectClass: shadowAccount
uid: testuser
cn: Test User
sn: User
givenName: Test
mail: testuser@example.org
uidNumber: 10000
gidNumber: 10000
homeDirectory: /home/testuser
userPassword: $TEST_USER_PASSWORD

dn: cn=openrbi-admins,ou=groups,dc=example,dc=org
objectClass: groupOfNames
cn: openrbi-admins
member: uid=testuser,ou=people,dc=example,dc=org
EOF

echo "[ldap-tests] seeded testuser + openrbi-admins group"

# pytest is a [dev]-only dependency (backend/pyproject.toml), not baked
# into the production image — matches scripts/run-integration-tests.sh's
# same on-demand install.
docker exec -u root "$BACKEND_CONTAINER" pip install --quiet ".[dev]"

docker cp "$SCRIPT_DIR/../backend/tests/integration/test_ldap_auth.py" "$BACKEND_CONTAINER:/app/test_ldap_auth.py"

MSYS_NO_PATHCONV=1 docker exec \
    -e OPENRBI_LDAP_ENABLED=true \
    -e OPENRBI_LDAP_SERVER_URI="ldaps://$LDAP_CONTAINER:636" \
    -e OPENRBI_LDAP_USE_STARTTLS=true \
    -e OPENRBI_LDAP_BIND_DN="cn=admin,dc=example,dc=org" \
    -e OPENRBI_LDAP_BIND_PASSWORD="$LDAP_ADMIN_PASSWORD" \
    -e OPENRBI_LDAP_BASE_DN="dc=example,dc=org" \
    -e OPENRBI_LDAP_USER_SEARCH_FILTER="(uid={username})" \
    -e OPENRBI_LDAP_TEST_USER_PASSWORD="$TEST_USER_PASSWORD" \
    -e LDAPTLS_REQCERT=never \
    "$BACKEND_CONTAINER" pytest -v -p no:cacheprovider /app/test_ldap_auth.py
