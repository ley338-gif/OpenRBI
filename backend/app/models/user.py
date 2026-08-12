import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class User(UUIDPKMixin, TimestampMixin, Base):
    """Referenced everywhere by stable UUID, never by username (see the
    project's non-negotiables: usernames must not be used as a technical
    primary key).
    """

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )
    role = relationship("Role")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Application-layer encrypted (see app.config.totp_secret_encryption_key),
    # not just relying on disk/DB encryption (docs/adr/0002-totp-mfa.md).
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)

    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
