"""Fast, no-fixture unit coverage for case-insensitive DN comparison
(app/core/ldap_dn.py) and the group->role resolution built on it
(app/services/ldap_provisioning.py). Unlike test_ldap_auth.py/
test_ldap_login_flow.py, these need no live LDAP server or DB — they run
in every normal `scripts/run-integration-tests.sh` pass, not only via the
dedicated LDAP scripts.
"""

import pytest

from app.core.ldap_dn import dns_equal, normalize_dn
from app.services.ldap_provisioning import resolve_role_from_ldap_groups


@pytest.mark.parametrize(
    "a,b,should_match",
    [
        (
            "cn=openrbi-admins,ou=groups,dc=example,dc=org",
            "CN=OpenRBI-Admins,OU=Groups,DC=Example,DC=ORG",
            True,
        ),
        (
            "cn=openrbi-admins,ou=groups,dc=example,dc=org",
            "cn=openrbi-admins,ou=groups,dc=example,dc=org",
            True,
        ),
        # Different group entirely — case-insensitivity must never widen
        # matching beyond the actual DN.
        (
            "cn=openrbi-admins,ou=groups,dc=example,dc=org",
            "cn=openrbi-users,ou=groups,dc=example,dc=org",
            False,
        ),
        # Different hierarchy depth/order is a different DN, not just
        # different case.
        (
            "cn=openrbi-admins,ou=groups,dc=example,dc=org",
            "cn=openrbi-admins,ou=other-groups,dc=example,dc=org",
            False,
        ),
    ],
)
def test_dns_equal_is_case_insensitive_but_still_exact_otherwise(a, b, should_match):
    assert dns_equal(a, b) is should_match


def test_normalize_dn_falls_back_to_lowercased_string_on_unparseable_input():
    # Malformed input must never raise out of a login path — it just never
    # matches anything real, which is the correct fail-closed outcome (no
    # elevated role from a mapping entry nobody could have validly typed
    # against a real directory).
    assert normalize_dn("not=a=valid==dn===") == normalize_dn("NOT=A=VALID==DN===")


def test_resolve_role_from_ldap_groups_matches_despite_case_difference():
    mapping = {"CN=OpenRBI-Admins,OU=Groups,DC=Example,DC=ORG": "ADMIN"}
    role = resolve_role_from_ldap_groups(
        ["cn=openrbi-admins,ou=groups,dc=example,dc=org"], mapping
    )
    assert role == "ADMIN"


def test_resolve_role_from_ldap_groups_defaults_to_user_with_no_match():
    mapping = {"cn=openrbi-admins,ou=groups,dc=example,dc=org": "ADMIN"}
    role = resolve_role_from_ldap_groups(
        ["cn=some-other-group,ou=groups,dc=example,dc=org"], mapping
    )
    assert role == "USER"
