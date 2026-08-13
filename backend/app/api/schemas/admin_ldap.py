"""Roadmap B1.8 — request/response shapes for the admin LDAP configuration
API (app/api/admin_ldap.py).

The bind password is structurally kept out of every response here: no
field on any response model can ever carry it, only a
`bind_password_configured: bool`. LdapConfigUpdateRequest.bind_password is
`str | None` and *optional* precisely so "field omitted" (keep existing
secret) is distinguishable from "field present but empty" — see
docs/adr/0016-ldap-admin-configuration.md.
"""

import uuid

from pydantic import BaseModel, Field, field_validator, model_validator


class _LdapConnectionFields(BaseModel):
    server_uri: str = Field(min_length=1, max_length=512)
    use_starttls: bool
    bind_dn: str = Field(max_length=512)
    base_dn: str = Field(max_length=512)
    user_search_filter: str = Field(min_length=1, max_length=512)
    group_attribute: str = Field(min_length=1, max_length=255)

    @field_validator("server_uri")
    @classmethod
    def validate_server_uri(cls, value: str) -> str:
        value = value.strip()
        if not value.lower().startswith(("ldap://", "ldaps://")):
            raise ValueError("Server URI must use ldap:// or ldaps://")
        return value

    @field_validator("base_dn")
    @classmethod
    def validate_base_dn(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Base DN is required")
        return value.strip()

    @field_validator("user_search_filter")
    @classmethod
    def validate_search_filter(cls, value: str) -> str:
        if "{username}" not in value:
            raise ValueError("User search filter must contain {username}")
        return value

    @model_validator(mode="after")
    def validate_tls_mode(self):
        if self.server_uri.lower().startswith("ldaps://") and self.use_starttls:
            raise ValueError("StartTLS cannot be combined with an ldaps:// URI")
        if self.server_uri.lower().startswith("ldap://") and not self.use_starttls:
            raise ValueError("Plain ldap:// requires StartTLS; unencrypted LDAP is not supported")
        return self


class LdapConfigResponse(BaseModel):
    enabled: bool
    server_uri: str
    use_starttls: bool
    bind_dn: str
    bind_password_configured: bool
    base_dn: str
    user_search_filter: str
    group_attribute: str
    group_role_mapping: dict[str, str]
    updated_by: uuid.UUID | None

    @classmethod
    def from_model(cls, row) -> "LdapConfigResponse":
        return cls(
            enabled=row.enabled,
            server_uri=row.server_uri,
            use_starttls=row.use_starttls,
            bind_dn=row.bind_dn,
            bind_password_configured=row.bind_password_encrypted is not None,
            base_dn=row.base_dn,
            user_search_filter=row.user_search_filter,
            group_attribute=row.group_attribute,
            group_role_mapping=row.group_role_mapping or {},
            updated_by=row.updated_by,
        )

    @classmethod
    def empty(cls) -> "LdapConfigResponse":
        """No row persisted yet — nothing configured, nothing to report."""
        return cls(
            enabled=False,
            server_uri="",
            use_starttls=True,
            bind_dn="",
            bind_password_configured=False,
            base_dn="",
            user_search_filter="(sAMAccountName={username})",
            group_attribute="memberOf",
            group_role_mapping={},
            updated_by=None,
        )


class LdapConfigUpdateRequest(_LdapConnectionFields):
    enabled: bool
    # Omitted -> keep the existing stored secret. Present and non-empty ->
    # replace it. Present and empty string is treated the same as omitted
    # (Section 4: an empty field on update must never clear the secret) —
    # enforced in the endpoint, not here, since that needs the existing row.
    bind_password: str | None = None
    group_role_mapping: dict[str, str] = Field(default_factory=dict)


class LdapTestRequest(_LdapConnectionFields):
    # Always required for a test call (never "keep the stored one") — the
    # test is stateless and never touches the DB, so there is no existing
    # secret to fall back to here.
    bind_password: str
    test_username: str | None = None


class LdapTestStepResponse(BaseModel):
    name: str
    ok: bool
    detail: str | None


class LdapTestResponse(BaseModel):
    success: bool
    steps: list[LdapTestStepResponse]
    groups_discovered: int | None
