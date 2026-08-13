import uuid

from sqlalchemy import Boolean, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin

# Roadmap B1.8 — single-row table: the admin portal manages exactly one
# LDAP configuration, not a list of named profiles (deliberately not a
# generic settings platform). A fixed, well-known primary key is a
# structural guarantee of "at most one row that matters" without needing a
# unique-constraint-plus-application-check dance — any upsert always
# targets this exact id.
LDAP_CONFIG_ID = uuid.UUID("00000000-0000-0000-0000-00000000c0c9")


class LdapConfig(TimestampMixin, Base):
    """Persisted LDAP configuration (docs/adr/0016-ldap-admin-configuration.md).

    bind_password_encrypted reuses app/core/crypto.py's existing Fernet
    helpers (the same OPENRBI_TOTP_SECRET_ENCRYPTION_KEY-derived key TOTP
    secrets are already encrypted with) rather than introducing a second
    secret-key concept — one encryption-at-rest story for the whole
    project, not two.

    Priority against the pre-existing env-var-only configuration
    (backend/app/config.py's Settings.ldap_*, Roadmap B1): once this row
    exists, it is authoritative — env vars are only ever consulted as a
    bootstrap/fallback when no row exists at all (app/services/
    ldap_config_service.py's get_effective_ldap_config), not merged or
    partially overridden field-by-field.
    """

    __tablename__ = "ldap_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=lambda: LDAP_CONFIG_ID)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    server_uri: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    use_starttls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    bind_dn: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # NULL until a real password has ever been saved. Never returned by any
    # API response — see app/api/schemas/admin_ldap.py.
    bind_password_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    base_dn: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    user_search_filter: Mapped[str] = mapped_column(String(512), nullable=False, default="(sAMAccountName={username})")
    group_attribute: Mapped[str] = mapped_column(String(255), nullable=False, default="memberOf")
    # Group DN -> OpenRBI role name, same shape and same exact-string-match
    # semantics as Settings.ldap_group_role_mapping (app/services/
    # ldap_provisioning.py's resolve_role_from_ldap_groups is unchanged by
    # B1.8 — only where the mapping value comes from changes).
    group_role_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
