"""Roadmap Phase B / B1.4-B1.6 — HTTP-level tests against the real
/auth/login endpoint with LDAP genuinely enabled, not just LdapAuthProvider
tested in isolation (that's backend/tests/integration/test_ldap_auth.py).
Run via `sh scripts/run-ldap-integration-tests.sh`, which starts a
throwaway LDAP server, seeds a pytest_-prefixed user mapped to ADMIN via
group membership, restarts the backend with OPENRBI_LDAP_* pointed at it,
runs this file, then restores the backend to its normal (LDAP-disabled)
configuration — these tests do nothing useful run any other way.

Covers the roadmap's own B1.6 test list:
  - B1.4: a mapped-to-ADMIN LDAP login enforces the same mandatory MFA
    enrollment a local ADMIN would get.
  - B1.6 (unreachable): stopping the real LDAP server mid-suite and
    confirming login is denied, not silently allowed — the HTTP-level
    version of test_ldap_auth.py's provider-level equivalent.
  - B1.5: a failed LDAP bind counts toward the exact same per-username
    lockout counter a failed local attempt would.
  - Regression: local login still works normally with LDAP enabled.
"""

import os

import pytest
from sqlalchemy import text

from tests.conftest import login_with_mfa_enrollment, make_user

LDAP_ADMIN_USERNAME = os.environ.get("OPENRBI_LDAP_TEST_ADMIN_USERNAME", "")
LDAP_ADMIN_PASSWORD = os.environ.get("OPENRBI_LDAP_TEST_ADMIN_PASSWORD", "")

pytestmark = pytest.mark.skipif(
    not (LDAP_ADMIN_USERNAME and LDAP_ADMIN_PASSWORD),
    reason="OPENRBI_LDAP_TEST_ADMIN_USERNAME/PASSWORD not set — run via scripts/run-ldap-integration-tests.sh",
)


@pytest.mark.asyncio
async def test_ldap_login_mapped_to_admin_requires_mfa_enrollment(db, client):
    """The actual property B1's roadmap entry names as an acceptance
    criterion: "MFA-Pflicht für privilegierte Rollen gilt für beide Wege."
    Reuses conftest's login_with_mfa_enrollment helper unchanged — if LDAP
    genuinely reaches the same enforcement point as local, the exact same
    helper that already verifies this for local ADMIN accounts works here
    too, with zero LDAP-specific logic of its own.
    """
    cookie = await login_with_mfa_enrollment(client, LDAP_ADMIN_USERNAME, LDAP_ADMIN_PASSWORD)
    assert cookie

    r = await client.get("/auth/me", cookies={"openrbi_session": cookie})
    r.raise_for_status()
    body = r.json()
    assert body["username"] == LDAP_ADMIN_USERNAME
    assert body["role"] == "ADMIN"
    assert body["mfa_enabled"] is True

    result = await db.execute(
        text("SELECT 1 FROM security_events WHERE event_type = 'USER_PROVISIONED_VIA_LDAP' "
             "AND metadata_json->>'username' = :username"),
        {"username": LDAP_ADMIN_USERNAME},
    )
    assert result.first() is not None


@pytest.mark.asyncio
async def test_local_login_still_works_with_ldap_enabled(db, client):
    # Regression check specifically *with* LDAP turned on — B1.1's own
    # suite already proves local is untouched with LDAP disabled
    # (the default); this proves the local-tried-first ordering in
    # login() doesn't break local accounts once a second provider exists.
    user, password = await make_user(db, role_name="USER")
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_failed_ldap_bind_counts_toward_the_same_lockout_as_local(client):
    from app.core.sessions import clear_login_failures

    await clear_login_failures(LDAP_ADMIN_USERNAME)

    for _ in range(10):
        r = await client.post(
            "/auth/login", json={"username": LDAP_ADMIN_USERNAME, "password": "definitely-wrong"}
        )
        assert r.status_code == 401

    # Even the *correct* password is now rejected — one shared lockout
    # counter, not a separate/weaker one for the LDAP path.
    r = await client.post(
        "/auth/login", json={"username": LDAP_ADMIN_USERNAME, "password": LDAP_ADMIN_PASSWORD}
    )
    assert r.status_code == 429

    await clear_login_failures(LDAP_ADMIN_USERNAME)


@pytest.mark.asyncio
async def test_ldap_server_unreachable_denies_login_no_fallback(client):
    """Deliberately does NOT stop/start the LDAP container itself — the
    backend has no Docker socket access at all (ADR 0005), so it cannot
    perform that operation, the same boundary scripts/run-security-tests.sh
    respects for its ClamAV-outage test. scripts/run-ldap-integration-
    tests.sh (running on the host) stops the container before invoking
    this one test by name and restarts it immediately after — this test
    only asserts the outcome.
    """
    r = await client.post(
        "/auth/login", json={"username": LDAP_ADMIN_USERNAME, "password": LDAP_ADMIN_PASSWORD}
    )
    # The account has no local password (JIT-provisioned, LDAP-only) —
    # local fails closed for the same reason a wrong password would,
    # LDAP fails closed because the server is unreachable. Never a 200.
    assert r.status_code == 401
