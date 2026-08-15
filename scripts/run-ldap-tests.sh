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

CERT_DIR="$SCRIPT_DIR/../.ldap-test-certs"

cleanup() {
    docker rm -f "$LDAP_CONTAINER" >/dev/null 2>&1 || true
    MSYS_NO_PATHCONV=1 docker exec -u root "$BACKEND_CONTAINER" \
        rm -f /app/test_ldap_auth.py /app/test_ldap_ca.crt /app/test_ldap_wrong_ca.crt >/dev/null 2>&1 || true
    rm -rf "$CERT_DIR"
}
trap cleanup EXIT

# LDAP_TLS=true makes the image generate and serve a self-signed cert on
# 636/StartTLS-on-389 at boot — real TLS, not a plaintext bind, so this
# test actually exercises the encrypted path app/config.py's startup
# validation requires. RBI-POST-001: LdapAuthProvider now always demands a
# verifiable certificate chain (OPT_X_TLS_REQUIRE_CERT=demand).
#
# osixia/openldap:1.5.0's own built-in cert generation reuses a CA bundled
# into the image at build time (2021) rather than minting a fresh one at
# container boot — that CA has since expired, so relying on it here would
# make every run fail with a real (and correctly rejected) expired-
# certificate error, not a bug in LdapAuthProvider. Generate our own
# short-lived CA + server cert on the runner instead and hand it to the
# container via LDAP_TLS_*_FILENAME before first start, then trust that CA
# via OPENRBI_LDAP_CA_CERT_FILE below — the same mechanism a real
# deployment against an internal/private CA would use.
docker rm -f "$LDAP_CONTAINER" >/dev/null 2>&1 || true
rm -rf "$CERT_DIR"
mkdir -p "$CERT_DIR"
openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
    -keyout "$CERT_DIR/ca.key" -out "$CERT_DIR/ca.crt" \
    -subj "/CN=OpenRBI Test CA" >/dev/null 2>&1
openssl req -newkey rsa:2048 -nodes \
    -keyout "$CERT_DIR/ldap.key" -out "$CERT_DIR/ldap.csr" \
    -subj "/CN=$LDAP_CONTAINER" >/dev/null 2>&1
printf 'subjectAltName=DNS:%s\n' "$LDAP_CONTAINER" > "$CERT_DIR/ldap.ext"
openssl x509 -req -in "$CERT_DIR/ldap.csr" -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial -out "$CERT_DIR/ldap.crt" -days 30 -extfile "$CERT_DIR/ldap.ext" >/dev/null 2>&1
chmod 644 "$CERT_DIR/ca.crt" "$CERT_DIR/ldap.crt"
chmod 600 "$CERT_DIR/ldap.key"

# --hostname: osixia/openldap's --hostname must still agree with the CN/SAN
# above and with the ldaps:// URI used to connect below, independent of
# which CA signed the cert.
docker create --name "$LDAP_CONTAINER" --hostname "$LDAP_CONTAINER" \
    --network openrbi_control-plane \
    -e LDAP_ORGANISATION="OpenRBI Test" \
    -e LDAP_DOMAIN="example.org" \
    -e LDAP_ADMIN_PASSWORD="$LDAP_ADMIN_PASSWORD" \
    -e LDAP_TLS=true \
    -e LDAP_TLS_VERIFY_CLIENT=never \
    -e LDAP_TLS_CRT_FILENAME=ldap.crt \
    -e LDAP_TLS_KEY_FILENAME=ldap.key \
    -e LDAP_TLS_CA_CRT_FILENAME=ca.crt \
    osixia/openldap:1.5.0 >/dev/null
docker cp "$CERT_DIR/ca.crt" "$LDAP_CONTAINER:/container/service/slapd/assets/certs/ca.crt"
docker cp "$CERT_DIR/ldap.crt" "$LDAP_CONTAINER:/container/service/slapd/assets/certs/ldap.crt"
docker cp "$CERT_DIR/ldap.key" "$LDAP_CONTAINER:/container/service/slapd/assets/certs/ldap.key"
docker start "$LDAP_CONTAINER" >/dev/null

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

# Hand the test client the CA we generated above (not one extracted from
# the container — we own it directly already) so it can trust the server's
# certificate explicitly, the same way a real deployment would trust an
# internal CA via OPENRBI_LDAP_CA_CERT_FILE (RBI-POST-001) — never via a
# blanket TLS-verification bypass.
docker cp "$CERT_DIR/ca.crt" "$BACKEND_CONTAINER:/app/test_ldap_ca.crt"

# A CA bundle unrelated to the test server's real CA — used to prove that
# a *wrong* CA is rejected exactly like no CA at all, never silently
# accepted just because some CA file was configured. Generated on the
# runner/host, not inside the backend container — the production backend
# image deliberately has no openssl CLI (Debian slim base, no reason to
# ship it), same as it has no docker socket or host access.
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -keyout "$CERT_DIR/wrong-ca.key" -out "$CERT_DIR/wrong-ca.crt" \
    -subj "/CN=openrbi-test-unrelated-ca" >/dev/null 2>&1
docker cp "$CERT_DIR/wrong-ca.crt" "$BACKEND_CONTAINER:/app/test_ldap_wrong_ca.crt"

# pytest is a [dev]-only dependency (backend/pyproject.toml), not baked
# into the production image — matches scripts/run-integration-tests.sh's
# same on-demand install.
docker exec -u root "$BACKEND_CONTAINER" \
    pip install --quiet --require-hashes -r requirements-dev.lock

docker cp "$SCRIPT_DIR/../backend/tests/integration/test_ldap_auth.py" "$BACKEND_CONTAINER:/app/test_ldap_auth.py"

# RBI-POST-001: TLS trust is read once, at module-import time, into the
# LDAPTLS_CACERT environment variable app/core/auth_providers/ldap.py sets
# up before `import ldap` — see test_ldap_auth.py's _config_from_env
# docstring. That means it can't be varied per-test-function within a
# single pytest process; each CA-trust scenario below is therefore its own
# fresh `pytest` invocation (a fresh process, a fresh module import) with a
# different OPENRBI_LDAP_CA_CERT_FILE, rather than a config override.
LDAP_TEST_COMMON_ENV="
    -e OPENRBI_LDAP_ENABLED=true
    -e OPENRBI_LDAP_SERVER_URI=ldaps://$LDAP_CONTAINER:636
    -e OPENRBI_LDAP_USE_STARTTLS=true
    -e OPENRBI_LDAP_BIND_DN=cn=admin,dc=example,dc=org
    -e OPENRBI_LDAP_BIND_PASSWORD=$LDAP_ADMIN_PASSWORD
    -e OPENRBI_LDAP_BASE_DN=dc=example,dc=org
    -e OPENRBI_LDAP_USER_SEARCH_FILTER=(uid={username})
    -e OPENRBI_LDAP_TEST_USER_PASSWORD=$TEST_USER_PASSWORD
"

echo "[ldap-tests] main run: correctly configured CA — full test file"
# shellcheck disable=SC2086
MSYS_NO_PATHCONV=1 docker exec $LDAP_TEST_COMMON_ENV \
    -e OPENRBI_LDAP_CA_CERT_FILE=/app/test_ldap_ca.crt \
    -e OPENRBI_LDAP_WRONG_CA_CERT_FILE=/app/test_ldap_wrong_ca.crt \
    "$BACKEND_CONTAINER" pytest -v -p no:cacheprovider /app/test_ldap_auth.py

echo "[ldap-tests] scenario run: no CA configured — untrusted self-signed cert must be rejected"
# shellcheck disable=SC2086
MSYS_NO_PATHCONV=1 docker exec $LDAP_TEST_COMMON_ENV \
    "$BACKEND_CONTAINER" pytest -v -p no:cacheprovider /app/test_ldap_auth.py \
    -k test_untrusted_certificate_is_rejected_without_a_configured_ca

echo "[ldap-tests] scenario run: wrong CA configured — must still be rejected"
# shellcheck disable=SC2086
MSYS_NO_PATHCONV=1 docker exec $LDAP_TEST_COMMON_ENV \
    -e OPENRBI_LDAP_CA_CERT_FILE=/app/test_ldap_wrong_ca.crt \
    -e OPENRBI_LDAP_WRONG_CA_CERT_FILE=/app/test_ldap_wrong_ca.crt \
    "$BACKEND_CONTAINER" pytest -v -p no:cacheprovider /app/test_ldap_auth.py \
    -k test_wrong_ca_cert_is_rejected
