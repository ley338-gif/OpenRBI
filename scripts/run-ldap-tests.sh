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
# OPENRBI_LDAP_CA_CERT_FILE override below only has to apply to *this*
# pytest process. The admin LDAP HTTP API (app/api/admin_ldap.py) is
# different: it runs inside the already-running uvicorn process, which
# needs its own TLS trust for this throwaway self-signed cert — that's
# covered by scripts/run-ldap-integration-tests.sh instead, which actually
# restarts the backend with the right environment (see test_admin_ldap.py
# there).
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
    MSYS_NO_PATHCONV=1 docker exec -u root "$BACKEND_CONTAINER" \
        rm -f /app/test_ldap_auth.py /app/test_ldap_ca.crt /app/test_ldap_wrong_ca.crt >/dev/null 2>&1 || true
}
trap cleanup EXIT

# LDAP_TLS=true makes the image generate and serve a self-signed cert on
# 636/StartTLS-on-389 at boot — real TLS, not a plaintext bind, so this
# test actually exercises the encrypted path app/config.py's startup
# validation requires. RBI-POST-001: LdapAuthProvider now always demands a
# verifiable certificate chain (OPT_X_TLS_REQUIRE_CERT=demand), so this
# throwaway server's own generated CA is extracted below and handed to the
# test client via OPENRBI_LDAP_CA_CERT_FILE — the exact same mechanism a
# real deployment against an internal/private CA would use — instead of
# the previous LDAPTLS_REQCERT=never blanket bypass.
docker rm -f "$LDAP_CONTAINER" >/dev/null 2>&1 || true
# --hostname matters now that certificate verification is real
# (RBI-POST-001): osixia/openldap generates its self-signed server
# certificate's CN/SAN from the container's own hostname at boot, and
# without this flag that defaults to the random container ID, not
# "$LDAP_CONTAINER" — the name actually used in
# OPENRBI_LDAP_SERVER_URI=ldaps://$LDAP_CONTAINER:636 below. A mismatch
# there fails the handshake even with the right CA trusted, since
# hostname verification is a separate check from chain-of-trust
# verification.
docker run -d --name "$LDAP_CONTAINER" --hostname "$LDAP_CONTAINER" \
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

# Extract the throwaway server's own generated CA cert (osixia/openldap
# writes its self-signed bundle here when LDAP_TLS=true and no certs are
# supplied) so the test client can trust it explicitly, the same way a
# real deployment would trust an internal CA via OPENRBI_LDAP_CA_CERT_FILE
# (RBI-POST-001) — not via a blanket TLS-verification bypass.
# /container/service/slapd/assets/certs/ca.crt is a symlink (to
# /container/service/:ssl-tools/assets/default-ca/default-ca.pem inside
# the container) — `docker cp` copies a symlink literally rather than
# following it, which produces a broken link on the host pointing at a
# path that only exists inside the container. `docker exec ... cat`
# reads it through the container's own filesystem instead, sidestepping
# that entirely.
docker exec "$LDAP_CONTAINER" cat /container/service/slapd/assets/certs/ca.crt \
    > "$SCRIPT_DIR/../backend/test_ldap_ca.crt"
echo "[ldap-tests] extracted CA cert:"
openssl x509 -in "$SCRIPT_DIR/../backend/test_ldap_ca.crt" -noout -subject -issuer -dates -ext subjectAltName || true
docker cp "$SCRIPT_DIR/../backend/test_ldap_ca.crt" "$BACKEND_CONTAINER:/app/test_ldap_ca.crt"
rm -f "$SCRIPT_DIR/../backend/test_ldap_ca.crt"

# A CA bundle unrelated to the test server's real CA — used to prove that
# a *wrong* CA is rejected exactly like no CA at all, never silently
# accepted just because some CA file was configured. Generated on the
# runner/host, not inside the backend container — the production backend
# image deliberately has no openssl CLI (Debian slim base, no reason to
# ship it), same as it has no docker socket or host access.
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -keyout "$SCRIPT_DIR/../backend/test_ldap_wrong_ca_key.pem" \
    -out "$SCRIPT_DIR/../backend/test_ldap_wrong_ca.crt" \
    -subj "/CN=openrbi-test-unrelated-ca" >/dev/null 2>&1
docker cp "$SCRIPT_DIR/../backend/test_ldap_wrong_ca.crt" "$BACKEND_CONTAINER:/app/test_ldap_wrong_ca.crt"
rm -f "$SCRIPT_DIR/../backend/test_ldap_wrong_ca_key.pem" "$SCRIPT_DIR/../backend/test_ldap_wrong_ca.crt"

# pytest is a [dev]-only dependency (backend/pyproject.toml), not baked
# into the production image — matches scripts/run-integration-tests.sh's
# same on-demand install.
docker exec -u root "$BACKEND_CONTAINER" \
    pip install --quiet --require-hashes -r requirements-dev.lock

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
    -e OPENRBI_LDAP_CA_CERT_FILE=/app/test_ldap_ca.crt \
    -e OPENRBI_LDAP_WRONG_CA_CERT_FILE=/app/test_ldap_wrong_ca.crt \
    "$BACKEND_CONTAINER" pytest -v -p no:cacheprovider /app/test_ldap_auth.py
