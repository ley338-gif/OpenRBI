"""Roadmap Phase B / B1.8 — resolves which LDAP configuration is actually
in effect for a given request: the persisted, admin-portal-editable
`LdapConfig` row if one exists, otherwise the pre-existing OPENRBI_LDAP_*
environment variables (Roadmap B1, unchanged) as a bootstrap/fallback for
deployments that haven't touched the admin UI yet.

Priority is deliberately simple and documented in one place (docs/adr/
0016-ldap-admin-configuration.md): once a database row exists, it is
authoritative in full — never merged field-by-field with the environment,
never "env overrides an empty DB field". A fresh install with no row yet
keeps working exactly as Roadmap B1 shipped it, purely from .env.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.auth_providers.ldap import LdapConnectionConfig
from app.core.crypto import decrypt_secret
from app.models.ldap_config import LDAP_CONFIG_ID, LdapConfig


def config_from_settings(settings: Settings) -> LdapConnectionConfig:
    return LdapConnectionConfig(
        server_uri=settings.ldap_server_uri,
        use_starttls=settings.ldap_use_starttls,
        bind_dn=settings.ldap_bind_dn,
        bind_password=settings.ldap_bind_password,
        base_dn=settings.ldap_base_dn,
        user_search_filter=settings.ldap_user_search_filter,
        group_attribute=settings.ldap_group_attribute,
        ca_cert_file=settings.ldap_ca_cert_file,
    )


def config_from_row(row: LdapConfig, bind_password: str) -> LdapConnectionConfig:
    # ca_cert_file is a deployment-level trust-store setting (mounted file,
    # OPENRBI_LDAP_CA_CERT_FILE), not admin-portal-editable per-row state —
    # it applies identically regardless of whether the DB row or the env
    # path is the effective config (RBI-POST-001).
    return LdapConnectionConfig(
        server_uri=row.server_uri,
        use_starttls=row.use_starttls,
        bind_dn=row.bind_dn,
        bind_password=bind_password,
        base_dn=row.base_dn,
        user_search_filter=row.user_search_filter,
        group_attribute=row.group_attribute,
        ca_cert_file=get_settings().ldap_ca_cert_file,
    )


async def get_ldap_config_row(db: AsyncSession) -> LdapConfig | None:
    return await db.get(LdapConfig, LDAP_CONFIG_ID)


async def get_effective_ldap_config(db: AsyncSession) -> LdapConnectionConfig | None:
    """None means "LDAP is off" — either explicitly (a saved row with
    enabled=False) or by omission (no row yet, and the env-var path is
    also disabled). Never partially resolves — see module docstring.
    """
    row = await get_ldap_config_row(db)
    if row is not None:
        if not row.enabled:
            return None
        password = decrypt_secret(row.bind_password_encrypted) if row.bind_password_encrypted else ""
        return config_from_row(row, password)

    settings = get_settings()
    if not settings.ldap_enabled:
        return None
    return config_from_settings(settings)


async def get_effective_group_role_mapping(db: AsyncSession) -> dict[str, str]:
    """Same DB-authoritative-once-it-exists priority as
    get_effective_ldap_config, but a separate lookup rather than a field on
    LdapConnectionConfig: the mapping is consulted at a different point in
    the login flow — after a successful bind, by app/services/
    ldap_provisioning.py's resolve_role_from_ldap_groups, not by
    LdapAuthProvider itself, which has no reason to know about roles at all.
    """
    row = await get_ldap_config_row(db)
    if row is not None:
        return row.group_role_mapping or {}
    return get_settings().ldap_group_role_mapping
