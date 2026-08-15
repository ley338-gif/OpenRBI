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

Roadmap B1.8: LdapAuthProvider now takes an explicit LdapConnectionConfig
instead of reading app.config.get_settings() internally (so it can serve
both the env-var path and the new admin-portal-configured DB path with
identical logic) — this file builds that config from the environment
directly, the same values the pre-B1.8 version read implicitly.
"""

import os

import pytest

from app.core.auth_providers.ldap import LdapAuthProvider, LdapConnectionConfig

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


def _config_from_env(**overrides) -> LdapConnectionConfig:
    # RBI-POST-001: unlike every other setting here, TLS trust
    # (OPENRBI_LDAP_CA_CERT_FILE) is NOT part of LdapConnectionConfig and
    # can't be varied per-test via an override — app/core/auth_providers/
    # ldap.py reads it once, at module-import time, into the
    # LDAPTLS_CACERT environment variable, because python-ldap's
    # underlying OpenLDAP C library only honors that variable if it's set
    # before the library is first loaded/used in the process; a later
    # os.environ mutation (even before the first connection) is silently
    # ignored. That's why this file's CA-trust scenarios
    # (test_untrusted_certificate_is_rejected_without_a_configured_ca,
    # test_wrong_ca_cert_is_rejected) are each run as their own separate
    # `pytest -k` invocation with a different OPENRBI_LDAP_CA_CERT_FILE set
    # on the process from the start (scripts/run-ldap-tests.sh) rather
    # than as ordinary test functions sharing this process's config.
    config = LdapConnectionConfig(
        server_uri=os.environ["OPENRBI_LDAP_SERVER_URI"],
        use_starttls=os.environ.get("OPENRBI_LDAP_USE_STARTTLS", "true").lower() == "true",
        bind_dn=os.environ["OPENRBI_LDAP_BIND_DN"],
        bind_password=os.environ["OPENRBI_LDAP_BIND_PASSWORD"],
        base_dn=os.environ["OPENRBI_LDAP_BASE_DN"],
        user_search_filter=os.environ.get("OPENRBI_LDAP_USER_SEARCH_FILTER", "(sAMAccountName={username})"),
        group_attribute=os.environ.get("OPENRBI_LDAP_GROUP_ATTRIBUTE", "memberOf"),
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


@pytest.mark.asyncio
async def test_correct_credentials_succeed():
    # Also the RBI-POST-001 "correctly configured internal CA succeeds"
    # acceptance case — this whole file's default process env
    # (scripts/run-ldap-tests.sh) has OPENRBI_LDAP_CA_CERT_FILE pointed at
    # the throwaway server's actual issuing CA.
    provider = LdapAuthProvider(_config_from_env())
    result = await provider.authenticate(None, TEST_USERNAME, TEST_PASSWORD)
    assert result.success is True
    assert result.username == TEST_USERNAME


@pytest.mark.asyncio
async def test_wrong_password_fails():
    provider = LdapAuthProvider(_config_from_env())
    result = await provider.authenticate(None, TEST_USERNAME, "definitely-the-wrong-password")
    assert result.success is False


@pytest.mark.asyncio
async def test_unknown_username_fails():
    provider = LdapAuthProvider(_config_from_env())
    result = await provider.authenticate(None, "no-such-user-exists", TEST_PASSWORD)
    assert result.success is False


@pytest.mark.asyncio
async def test_empty_password_fails_without_attempting_an_anonymous_bind():
    # Some directories treat an empty password as a valid anonymous bind,
    # which would otherwise "succeed" without checking anything at all.
    provider = LdapAuthProvider(_config_from_env())
    result = await provider.authenticate(None, TEST_USERNAME, "")
    assert result.success is False


@pytest.mark.asyncio
async def test_ldap_filter_injection_attempt_does_not_widen_the_search():
    # A username containing filter metacharacters must be escaped, not
    # interpolated raw into the LDAP search filter — otherwise
    # "*)(uid=*" style input could match every entry instead of none.
    provider = LdapAuthProvider(_config_from_env())
    result = await provider.authenticate(None, "*)(uid=*", TEST_PASSWORD)
    assert result.success is False


@pytest.mark.asyncio
async def test_unreachable_ldap_server_fails_closed():
    # The core fail-closed guarantee (docs/adr/0015): an LDAP outage must
    # deny the login, never fall back to any outcome that grants access.
    provider = LdapAuthProvider(_config_from_env(server_uri="ldaps://this-host-does-not-exist.invalid:636"))
    result = await provider.authenticate(None, TEST_USERNAME, TEST_PASSWORD)
    assert result.success is False


@pytest.mark.asyncio
async def test_health_check_reflects_real_server_state():
    provider = LdapAuthProvider(_config_from_env())
    assert await provider.health() is True

    broken_provider = LdapAuthProvider(_config_from_env(server_uri="ldaps://this-host-does-not-exist.invalid:636"))
    assert await broken_provider.health() is False


@pytest.mark.asyncio
async def test_test_connection_reports_each_step_and_discovers_groups():
    # Roadmap B1.8's "Test LDAP configuration" feature reuses this exact
    # method — verified here against the real server, independent of the
    # admin API that will call it (backend/tests/integration/
    # test_admin_ldap.py covers that HTTP layer).
    provider = LdapAuthProvider(_config_from_env())
    result = await provider.test_connection(test_username=TEST_USERNAME)
    assert result.success is True
    step_names = [s.name for s in result.steps]
    assert "TLS / connection" in step_names
    assert "Service bind" in step_names
    assert "Search base" in step_names
    assert "User search" in step_names
    assert "Group resolution" in step_names
    assert all(s.ok for s in result.steps)
    assert result.groups_discovered is not None


@pytest.mark.asyncio
async def test_untrusted_certificate_is_rejected_without_a_configured_ca():
    # RBI-POST-001 acceptance: this throwaway server's certificate is
    # self-signed and not in the OS trust store — run via scripts/
    # run-ldap-tests.sh as its own process with OPENRBI_LDAP_CA_CERT_FILE
    # deliberately left unset (the same as a real deployment that never
    # configured one), so the TLS handshake must fail closed exactly like
    # any other connection failure, never silently succeed because "it's
    # just a test server". See _config_from_env's docstring for why this
    # can't be expressed as a per-test override instead.
    if os.environ.get("OPENRBI_LDAP_CA_CERT_FILE"):
        pytest.skip("this process has a CA configured — run via scripts/run-ldap-tests.sh's dedicated invocation")
    provider = LdapAuthProvider(_config_from_env())
    result = await provider.authenticate(None, TEST_USERNAME, TEST_PASSWORD)
    assert result.success is False


@pytest.mark.asyncio
async def test_wrong_ca_cert_is_rejected():
    # RBI-POST-001 acceptance: configuring *a* CA file is not the same as
    # configuring the *right* CA file — run via scripts/run-ldap-tests.sh
    # as its own process with OPENRBI_LDAP_CA_CERT_FILE pointed at a CA
    # unrelated to the server's actual issuing CA, proving the configured
    # CA is verified, not merely present-checked.
    expected_wrong_ca = os.environ.get("OPENRBI_LDAP_WRONG_CA_CERT_FILE", "")
    if not expected_wrong_ca or os.environ.get("OPENRBI_LDAP_CA_CERT_FILE") != expected_wrong_ca:
        pytest.skip("this process isn't configured with the wrong-CA scenario — run via scripts/run-ldap-tests.sh")
    provider = LdapAuthProvider(_config_from_env())
    result = await provider.authenticate(None, TEST_USERNAME, TEST_PASSWORD)
    assert result.success is False


@pytest.mark.asyncio
async def test_test_connection_reports_friendly_error_on_unreachable_server():
    # ldap.initialize() is lazy for an ldaps:// URI — it doesn't actually
    # open a connection until the first real operation, so "TLS /
    # connection" trivially passes and the real failure surfaces at
    # "Service bind" instead. Asserting on *which* step failed rather than
    # assuming it's always the first one — that assumption doesn't hold
    # for every URI scheme/step combination.
    provider = LdapAuthProvider(_config_from_env(server_uri="ldaps://this-host-does-not-exist.invalid:636"))
    result = await provider.test_connection()
    assert result.success is False
    failed_steps = [s for s in result.steps if not s.ok]
    assert len(failed_steps) == 1
    assert "Traceback" not in (failed_steps[0].detail or "")
    assert "could not reach" in failed_steps[0].detail.lower()
