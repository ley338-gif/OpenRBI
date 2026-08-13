"""Roadmap B1.8.2/B1.8.5 — the admin LDAP configuration HTTP API
(app/api/admin_ldap.py), against a real, throwaway LDAP server (same
osixia/openldap instance test_ldap_auth.py uses — see
scripts/run-ldap-tests.sh, which copies both files into the running
backend container and runs them together). Not a mock: "successful
connection test" and "enabling requires a passing test" both need a
directory that genuinely answers a bind/search.

The persisted config is a single fixed-row table (app/models/ldap_config.py),
not per-test-prefixed data like tests/conftest.py's PREFIX convention
assumes — _reset_ldap_config below deletes that one row before and after
every test in this file so tests stay isolated from each other and don't
leave state behind in the shared dev database.
"""

import os

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.core.crypto import decrypt_secret
from app.models.ldap_config import LDAP_CONFIG_ID, LdapConfig
from tests.conftest import login_with_mfa_enrollment, make_user

LDAP_SERVER_URI = os.environ.get("OPENRBI_LDAP_SERVER_URI", "")
LDAP_BIND_DN = os.environ.get("OPENRBI_LDAP_BIND_DN", "")
LDAP_BIND_PASSWORD = os.environ.get("OPENRBI_LDAP_BIND_PASSWORD", "")
LDAP_BASE_DN = os.environ.get("OPENRBI_LDAP_BASE_DN", "")
LDAP_USER_SEARCH_FILTER = os.environ.get("OPENRBI_LDAP_USER_SEARCH_FILTER", "(uid={username})")
LDAP_TEST_USER_PASSWORD = os.environ.get("OPENRBI_LDAP_TEST_USER_PASSWORD", "")
# Set by scripts/run-ldap-integration-tests.sh to the username it actually
# seeded on the throwaway directory — scripts/run-ldap-tests.sh's own
# "testuser" is not guaranteed to exist under whichever runner invoked this
# file, so the probe username for /admin/ldap/test's optional user-search
# step is read from the environment rather than hardcoded.
LDAP_TEST_PROBE_USERNAME = os.environ.get("OPENRBI_LDAP_TEST_ADMIN_USERNAME") or None

pytestmark = pytest.mark.skipif(
    not LDAP_SERVER_URI, reason="OPENRBI_LDAP_SERVER_URI not set — run via scripts/run-ldap-tests.sh"
)


def _valid_payload(**overrides) -> dict:
    payload = {
        "enabled": False,
        "server_uri": LDAP_SERVER_URI,
        "use_starttls": True,
        "bind_dn": LDAP_BIND_DN,
        "bind_password": LDAP_BIND_PASSWORD,
        "base_dn": LDAP_BASE_DN,
        "user_search_filter": LDAP_USER_SEARCH_FILTER,
        "group_attribute": "memberOf",
        "group_role_mapping": {},
    }
    payload.update(overrides)
    return payload


@pytest_asyncio.fixture(autouse=True)
async def _reset_ldap_config(db):
    await db.execute(delete(LdapConfig).where(LdapConfig.id == LDAP_CONFIG_ID))
    await db.commit()
    yield
    await db.execute(delete(LdapConfig).where(LdapConfig.id == LDAP_CONFIG_ID))
    await db.commit()


@pytest.mark.asyncio
async def test_non_admin_cannot_read_or_change_config(db, client):
    user, password = await make_user(db, role_name="USER")
    # USER never has mandatory MFA — plain login applies.
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    cookie = r.cookies.get("openrbi_session")

    r = await client.get("/admin/ldap/config", cookies={"openrbi_session": cookie})
    assert r.status_code == 403

    r = await client.put("/admin/ldap/config", json=_valid_payload(), cookies={"openrbi_session": cookie})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_read_empty_config(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    r = await client.get("/admin/ldap/config", cookies={"openrbi_session": cookie})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["bind_password_configured"] is False
    assert "bind_password" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"server_uri": "https://directory.example.org"}, "ldap:// or ldaps://"),
        ({"base_dn": ""}, "Base DN"),
        ({"user_search_filter": "(uid=someone)"}, "{username}"),
        ({"server_uri": "ldaps://directory.example.org:636", "use_starttls": True}, "StartTLS"),
        ({"server_uri": "ldap://directory.example.org:389", "use_starttls": False}, "requires StartTLS"),
    ],
)
async def test_invalid_connection_settings_are_rejected_before_ldap_access(db, client, overrides, expected_message):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    response = await client.put(
        "/admin/ldap/config",
        json=_valid_payload(**overrides),
        cookies={"openrbi_session": cookie},
    )

    assert response.status_code == 422
    assert expected_message in response.text
    assert await db.get(LdapConfig, LDAP_CONFIG_ID) is None


@pytest.mark.asyncio
async def test_response_never_includes_bind_password(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    r = await client.put(
        "/admin/ldap/config", json=_valid_payload(enabled=False), cookies={"openrbi_session": cookie}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "bind_password" not in body
    assert body["bind_password_configured"] is True
    assert LDAP_BIND_PASSWORD not in r.text


@pytest.mark.asyncio
async def test_update_without_password_keeps_existing_secret(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    r = await client.put(
        "/admin/ldap/config", json=_valid_payload(enabled=False), cookies={"openrbi_session": cookie}
    )
    assert r.status_code == 200, r.text

    # Update again, omitting bind_password entirely — must not clear it.
    payload = _valid_payload(enabled=False)
    del payload["bind_password"]
    r = await client.put("/admin/ldap/config", json=payload, cookies={"openrbi_session": cookie})
    assert r.status_code == 200, r.text
    assert r.json()["bind_password_configured"] is True

    row = await db.get(LdapConfig, LDAP_CONFIG_ID)
    assert decrypt_secret(row.bind_password_encrypted) == LDAP_BIND_PASSWORD


@pytest.mark.asyncio
async def test_explicit_new_password_replaces_existing_secret(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    r = await client.put(
        "/admin/ldap/config", json=_valid_payload(enabled=False), cookies={"openrbi_session": cookie}
    )
    assert r.status_code == 200, r.text

    r = await client.put(
        "/admin/ldap/config",
        json=_valid_payload(enabled=False, bind_password="a-different-password"),
        cookies={"openrbi_session": cookie},
    )
    assert r.status_code == 200, r.text

    row = await db.get(LdapConfig, LDAP_CONFIG_ID)
    assert decrypt_secret(row.bind_password_encrypted) == "a-different-password"


@pytest.mark.asyncio
async def test_stateless_test_endpoint_does_not_persist_anything(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    r = await client.post(
        "/admin/ldap/test",
        json=_valid_payload(server_uri="ldaps://this-host-does-not-exist.invalid:636")
        | {"test_username": None},
        cookies={"openrbi_session": cookie},
    )
    assert r.status_code == 200, r.text
    assert r.json()["success"] is False
    assert "Traceback" not in r.text

    row = await db.get(LdapConfig, LDAP_CONFIG_ID)
    assert row is None


@pytest.mark.asyncio
async def test_successful_test_connection_reports_ok(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    r = await client.post(
        "/admin/ldap/test",
        json=_valid_payload() | {"test_username": LDAP_TEST_PROBE_USERNAME},
        cookies={"openrbi_session": cookie},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert all(step["ok"] for step in body["steps"])


@pytest.mark.asyncio
async def test_enabling_with_broken_config_is_rejected_and_leaves_active_config_untouched(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    # Save a working, enabled config first.
    r = await client.put("/admin/ldap/config", json=_valid_payload(enabled=True), cookies={"openrbi_session": cookie})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True

    # Attempt to update to a broken server while staying enabled.
    r = await client.put(
        "/admin/ldap/config",
        json=_valid_payload(enabled=True, server_uri="ldaps://this-host-does-not-exist.invalid:636"),
        cookies={"openrbi_session": cookie},
    )
    assert r.status_code == 422, r.text
    assert "Traceback" not in r.text

    # The previously-saved, working config must be untouched.
    row = await db.get(LdapConfig, LDAP_CONFIG_ID)
    assert row.enabled is True
    assert row.server_uri == LDAP_SERVER_URI


@pytest.mark.asyncio
async def test_enable_disable_round_trip_and_group_role_mapping_persists(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    mapping = {"cn=openrbi-admins,ou=groups,dc=example,dc=org": "ADMIN"}
    r = await client.put(
        "/admin/ldap/config",
        json=_valid_payload(enabled=True, group_role_mapping=mapping),
        cookies={"openrbi_session": cookie},
    )
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
    assert r.json()["group_role_mapping"] == mapping

    r = await client.put(
        "/admin/ldap/config", json=_valid_payload(enabled=False, group_role_mapping=mapping), cookies={"openrbi_session": cookie}
    )
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False
    assert r.json()["group_role_mapping"] == mapping
