import uuid

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import SecurityEventType
from app.models.mixins import CreatedAtMixin, UUIDPKMixin


class SecurityEvent(UUIDPKMixin, CreatedAtMixin, Base):
    """Append-only. No UPDATE/DELETE path is exposed anywhere in the admin
    API (see docs/security-model.md#audit). `metadata_json` must never
    contain passwords, MFA secrets, complete tokens, or file contents.
    """

    __tablename__ = "security_events"

    event_type: Mapped[SecurityEventType] = mapped_column(
        Enum(SecurityEventType, name="security_event_type"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("browser_sessions.id"), index=True
    )
    quarantine_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quarantine_files.id")
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
