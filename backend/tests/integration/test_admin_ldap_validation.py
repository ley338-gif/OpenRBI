import pytest
from pydantic import ValidationError

from app.api.schemas.admin_ldap import LdapConfigUpdateRequest


def valid_payload(**overrides) -> dict:
    payload = {
        "enabled": False,
        "server_uri": "ldap://directory.example.org:389",
        "use_starttls": True,
        "bind_dn": "cn=bind,dc=example,dc=org",
        "base_dn": "dc=example,dc=org",
        "user_search_filter": "(uid={username})",
        "group_attribute": "memberOf",
        "group_role_mapping": {},
    }
    payload.update(overrides)
    return payload


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
def test_invalid_connection_settings_are_rejected(overrides, expected_message):
    with pytest.raises(ValidationError) as exc_info:
        LdapConfigUpdateRequest.model_validate(valid_payload(**overrides))

    assert expected_message in str(exc_info.value)


def test_secure_ldap_transport_modes_are_accepted():
    starttls = LdapConfigUpdateRequest.model_validate(valid_payload())
    ldaps = LdapConfigUpdateRequest.model_validate(
        valid_payload(server_uri="ldaps://directory.example.org:636", use_starttls=False)
    )

    assert starttls.use_starttls is True
    assert ldaps.use_starttls is False
