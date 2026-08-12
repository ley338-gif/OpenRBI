"""Roadmap Phase B / B1.2/B1.6 — LdapAuthProvider against a real, throwaway
LDAP server (scripts/run-ldap-tests.sh starts osixia/openldap, seeds one
test user, and sets the OPENRBI_LDAP_* environment this file reads), not a
mock. Run via `sh scripts/run-ldap-tests.sh` — these tests do nothing
useful run any other way, since they depend on that seeded server actually
being up.

Does not touch Postgres/Redis — LdapAuthProvider itself has no DB
dependency (group-to-role mapping and JIT provisioning are Roadmap B1.3/
B1.4, layered on top in app/api/auth.py, not in the provider), so `db` is
passed as None throughout, matching the AuthProvider protocol's signature
without needing a real session for what this file actually exercises.
"""

import os

import pytest

from app.core.auth_providers.ldap import LdapAuthProvider

TEST_USERNAME = "testuser"
TEST_PASSWORD = os.environ.get("OPENRBI_LDAP_TEST_USER_PASSWORD", "")

# scripts/run-integration-tests.sh copies the whole backend/tests/ tree and
# runs pytest against it — this file would otherwise error out there with
# no LDAP server configured/reachable at all (LDAP is disabled by default,
# docs/adr/0015). Skip cleanly instead of erroring when this file's own
# runner (scripts/run-ldap-tests.sh) hasn't set up its throwaway server.
pytestmark = pytest.mark.skipif(
    not TEST_PASSWORD, reason="OPENRBI_LDAP_TEST_USER_PASSWORD not set — run via scripts/run-ldap-tests.sh"
)


@pytest.mark.asyncio
async def test_correct_credentials_succeed():
    provider = LdapAuthProvider()
    result = await provider.authenticate(None, TEST_USERNAME, TEST_PASSWORD)
    assert result.success is True
    assert result.username == TEST_USERNAME


@pytest.mark.asyncio
async def test_wrong_password_fails():
    provider = LdapAuthProvider()
    result = await provider.authenticate(None, TEST_USERNAME, "definitely-the-wrong-password")
    assert result.success is False


@pytest.mark.asyncio
async def test_unknown_username_fails():
    provider = LdapAuthProvider()
    result = await provider.authenticate(None, "no-such-user-exists", TEST_PASSWORD)
    assert result.success is False


@pytest.mark.asyncio
async def test_empty_password_fails_without_attempting_an_anonymous_bind():
    # Some directories treat an empty password as a valid anonymous bind,
    # which would otherwise "succeed" without checking anything at all.
    provider = LdapAuthProvider()
    result = await provider.authenticate(None, TEST_USERNAME, "")
    assert result.success is False


@pytest.mark.asyncio
async def test_ldap_filter_injection_attempt_does_not_widen_the_search():
    # A username containing filter metacharacters must be escaped, not
    # interpolated raw into the LDAP search filter — otherwise
    # "*)(uid=*" style input could match every entry instead of none.
    provider = LdapAuthProvider()
    result = await provider.authenticate(None, "*)(uid=*", TEST_PASSWORD)
    assert result.success is False


@pytest.mark.asyncio
async def test_unreachable_ldap_server_fails_closed(monkeypatch):
    # The core fail-closed guarantee (docs/adr/0015): an LDAP outage must
    # deny the login, never fall back to any outcome that grants access.
    # Patches app.core.auth_providers.ldap's own `get_settings` name
    # specifically — `from app.config import get_settings` binds a local
    # reference at import time, so patching app.config's attribute
    # wouldn't affect what this module already imported.
    from app.config import get_settings

    broken_settings = get_settings().model_copy(
        update={"ldap_server_uri": "ldaps://this-host-does-not-exist.invalid:636"}
    )
    monkeypatch.setattr("app.core.auth_providers.ldap.get_settings", lambda: broken_settings)

    provider = LdapAuthProvider()
    result = await provider.authenticate(None, TEST_USERNAME, TEST_PASSWORD)
    assert result.success is False


@pytest.mark.asyncio
async def test_health_check_reflects_real_server_state(monkeypatch):
    provider = LdapAuthProvider()
    assert await provider.health() is True

    from app.config import get_settings

    broken_settings = get_settings().model_copy(
        update={"ldap_server_uri": "ldaps://this-host-does-not-exist.invalid:636"}
    )
    monkeypatch.setattr("app.core.auth_providers.ldap.get_settings", lambda: broken_settings)
    broken_provider = LdapAuthProvider()
    assert await broken_provider.health() is False
