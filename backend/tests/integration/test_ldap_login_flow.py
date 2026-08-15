"""Roadmap Phase B / B1.4-B1.6 — HTTP-level tests against the real
/auth/login endpoint with LDAP genuinely enabled, not just LdapAuthProvider
tested in isolation (that's backend/tests/integration/test_ldap_auth.py).
Run via `sh scripts/run-ldap-integration-tests.sh`, which starts a
throwaway LDAP server, seeds a pytest_-prefixed user mapped to ADMIN via
group membership, starts a separate throwaway backend from the existing
Compose image with OPENRBI_LDAP_* pointed at it, then runs this file. The
normal backend and .env remain untouched — these tests do nothing useful
run any other way.

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
from sqlalchemy import select, text

from app.core.security import hash_password
from app.models.role import Role
from app.models.user import User
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
async def test_ldap_password_cannot_enter_same_named_local_admin(db, client):
    # Ensure the directory identity has a reconciled row, then turn that row
    # into an explicitly local, password-bearing ADMIN. The directory's
    # different password must no longer be a fallback for this username.
    await client.post(
        "/auth/login", json={"username": LDAP_ADMIN_USERNAME, "password": LDAP_ADMIN_PASSWORD}
    )
    user = await db.scalar(select(User).where(User.username == LDAP_ADMIN_USERNAME))
    admin_role = await db.scalar(select(Role).where(Role.name == "ADMIN"))
    assert user is not None and admin_role is not None
    original_hash, original_role_id = user.password_hash, user.role_id
    local_password = "Collision-Local-Password-2026!"
    user.password_hash = hash_password(local_password)
    user.role_id = admin_role.id
    await db.commit()
    try:
        r = await client.post(
            "/auth/login", json={"username": LDAP_ADMIN_USERNAME, "password": LDAP_ADMIN_PASSWORD}
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "invalid credentials"

        r = await client.post(
            "/auth/login", json={"username": LDAP_ADMIN_USERNAME, "password": local_password}
        )
        assert r.status_code == 200
        assert r.json()["status"] in {"mfa_required", "mfa_enrollment_required"}
    finally:
        user.password_hash = original_hash
        user.role_id = original_role_id
        await db.commit()


@pytest.mark.asyncio
async def test_disabled_ldap_identity_cannot_receive_a_session(db, client):
    await client.post(
        "/auth/login", json={"username": LDAP_ADMIN_USERNAME, "password": LDAP_ADMIN_PASSWORD}
    )
    user = await db.scalar(select(User).where(User.username == LDAP_ADMIN_USERNAME))
    assert user is not None
    user.is_active = False
    await db.commit()
    try:
        r = await client.post(
            "/auth/login", json={"username": LDAP_ADMIN_USERNAME, "password": LDAP_ADMIN_PASSWORD}
        )
        assert r.status_code == 401
        assert "openrbi_session" not in r.cookies
    finally:
        user.is_active = True
        await db.commit()


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
async def test_admin_editable_group_role_mapping_is_used_at_real_login(db, client):
    """Roadmap B1.8 regression coverage: resolve_role_from_ldap_groups was
    originally wired to always read Settings.ldap_group_role_mapping (the
    env var), so an admin-portal-saved mapping in ldap_configs was silently
    ignored by the real login path — found and fixed while building this
    test, not assumed correct. Proves the DB-persisted mapping (via
    PUT /admin/ldap/config) actually changes the role a real LDAP login
    resolves to, not just what GET returns.
    """
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)

    ldap_group_dn = "cn=openrbi-admins,ou=groups,dc=example,dc=org"
    payload = {
        "enabled": True,
        "server_uri": os.environ["OPENRBI_LDAP_SERVER_URI"],
        # False, not read from OPENRBI_LDAP_USE_STARTTLS: that env var is
        # "true" for this throwaway server's own startup config, but the
        # admin API's own validator correctly rejects StartTLS combined
        # with an already-TLS ldaps:// URI (StartTLS is only meaningful
        # for upgrading a plain ldap:// connection) — this test's payload
        # was simply stale, not a real bug in the validator or the
        # feature under test. Found while verifying the new isolated
        # ldap-integration-tests CI job actually runs this test, not
        # assumed from reading the code.
        "use_starttls": False,
        "bind_dn": os.environ["OPENRBI_LDAP_BIND_DN"],
        "bind_password": os.environ["OPENRBI_LDAP_BIND_PASSWORD"],
        "base_dn": os.environ["OPENRBI_LDAP_BASE_DN"],
        "user_search_filter": os.environ.get("OPENRBI_LDAP_USER_SEARCH_FILTER", "(uid={username})"),
        "group_attribute": os.environ.get("OPENRBI_LDAP_GROUP_ATTRIBUTE", "memberOf"),
        # Deliberately different from the env's OPENRBI_LDAP_GROUP_ROLE_MAPPING
        # (which maps this same group to ADMIN) — if the login path still
        # reads the env var, this test's own assertion below fails.
        "group_role_mapping": {ldap_group_dn: "SECURITY_REVIEWER"},
    }
    try:
        r = await client.put("/admin/ldap/config", json=payload, cookies={"openrbi_session": admin_cookie})
        assert r.status_code == 200, r.text

        # LDAP_ADMIN_USERNAME already completed MFA enrollment in an
        # earlier test in this file, so this attempt returns mfa_required,
        # not mfa_enrollment_required/ok — but role resolution and its
        # commit happen before that branch in app/api/auth.py's login(),
        # so the DB is already updated by the time this response returns.
        r = await client.post(
            "/auth/login", json={"username": LDAP_ADMIN_USERNAME, "password": LDAP_ADMIN_PASSWORD}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "mfa_required"

        result = await db.execute(
            text("SELECT r.name FROM users u JOIN roles r ON r.id = u.role_id WHERE u.username = :u"),
            {"u": LDAP_ADMIN_USERNAME},
        )
        assert result.scalar_one() == "SECURITY_REVIEWER"
    finally:
        # Leaves the DB config removed (falls back to the env mapping,
        # which maps this user back to ADMIN) so this test doesn't change
        # what any later test in this file/session observes.
        await db.execute(text("DELETE FROM ldap_configs"))
        await db.commit()


@pytest.mark.asyncio
async def test_group_role_mapping_is_case_insensitive_on_dn(db, client):
    """Regression test for the case-sensitive DN comparison bug
    (app/core/ldap_dn.py, app/services/ldap_provisioning.py): the group is
    seeded in this test LDAP server as
    "cn=openrbi-admins,ou=groups,dc=example,dc=org" (lowercase, see
    scripts/run-ldap-integration-tests.sh's ldapadd block), but the
    group->role mapping saved through the admin API here deliberately uses
    a completely different, uppercase-and-mixed-case spelling of the exact
    same DN. A directory that normalizes case differently than however an
    admin happened to type a mapping (Active Directory is known to do
    this) must not silently leave that mapping dead — the real LDAP
    bind's real memberOf attribute is what's compared here, not a
    synthetic string.
    """
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)

    mismatched_case_dn = "CN=OpenRBI-Admins,OU=Groups,DC=Example,DC=ORG"
    payload = {
        "enabled": True,
        "server_uri": os.environ["OPENRBI_LDAP_SERVER_URI"],
        # False, not read from OPENRBI_LDAP_USE_STARTTLS: that env var is
        # "true" for this throwaway server's own startup config, but the
        # admin API's own validator correctly rejects StartTLS combined
        # with an already-TLS ldaps:// URI (StartTLS is only meaningful
        # for upgrading a plain ldap:// connection) — a real, pre-existing,
        # unrelated inconsistency between backend startup config and this
        # endpoint's validation, flagged separately, not this test's
        # concern to work around by reproducing it.
        "use_starttls": False,
        "bind_dn": os.environ["OPENRBI_LDAP_BIND_DN"],
        "bind_password": os.environ["OPENRBI_LDAP_BIND_PASSWORD"],
        "base_dn": os.environ["OPENRBI_LDAP_BASE_DN"],
        "user_search_filter": os.environ.get("OPENRBI_LDAP_USER_SEARCH_FILTER", "(uid={username})"),
        "group_attribute": os.environ.get("OPENRBI_LDAP_GROUP_ATTRIBUTE", "memberOf"),
        "group_role_mapping": {mismatched_case_dn: "ADMIN"},
    }
    try:
        r = await client.put("/admin/ldap/config", json=payload, cookies={"openrbi_session": admin_cookie})
        assert r.status_code == 200, r.text

        r = await client.post(
            "/auth/login", json={"username": LDAP_ADMIN_USERNAME, "password": LDAP_ADMIN_PASSWORD}
        )
        assert r.status_code == 200
        # mfa_required, not mfa_enrollment_required: this account already
        # completed enrollment in an earlier test in this file — but role
        # resolution and its DB commit happen before that branch in
        # app/api/auth.py's login(), so the role is already updated.
        assert r.json()["status"] == "mfa_required"

        result = await db.execute(
            text("SELECT r.name FROM users u JOIN roles r ON r.id = u.role_id WHERE u.username = :u"),
            {"u": LDAP_ADMIN_USERNAME},
        )
        assert result.scalar_one() == "ADMIN"
    finally:
        await db.execute(text("DELETE FROM ldap_configs"))
        await db.commit()


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
