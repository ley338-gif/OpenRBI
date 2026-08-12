import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import FileAction, QuarantineStatus, ScannerStatus
from app.models.mixins import CreatedAtMixin, UUIDPKMixin


class QuarantineFile(UUIDPKMixin, CreatedAtMixin, Base):
    """See docs/quarantine.md. Never stored under its original filename on
    disk — `storage_object_id` is the content-addressed/opaque key into
    quarantine storage; all descriptive metadata lives here instead.
    """

    __tablename__ = "quarantine_files"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("browser_sessions.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    original_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    extension: Mapped[str | None] = mapped_column(String(32))
    declared_mime: Mapped[str | None] = mapped_column(String(255))
    detected_mime: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    initial_url: Mapped[str | None] = mapped_column(String(2048))
    final_url: Mapped[str | None] = mapped_column(String(2048))
    source_host: Mapped[str | None] = mapped_column(String(255), index=True)
    redirect_chain: Mapped[list | None] = mapped_column(JSONB)
    tls_used: Mapped[bool | None] = mapped_column(Boolean)

    scanner_status: Mapped[ScannerStatus] = mapped_column(
        Enum(ScannerStatus, name="scanner_status"), nullable=False, default=ScannerStatus.PENDING
    )
    scanner_result: Mapped[str | None] = mapped_column(String(1024))

    policy_action: Mapped[FileAction | None] = mapped_column(Enum(FileAction, name="file_action_result"))
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_versions.id")
    )

    status: Mapped[QuarantineStatus] = mapped_column(
        Enum(QuarantineStatus, name="quarantine_status"), nullable=False,
        default=QuarantineStatus.PENDING_SCAN,
    )
    storage_object_id: Mapped[str | None] = mapped_column(String(255))

    reviewed_at: Mapped[datetime | None] = mapped_column()
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    review_comment: Mapped[str | None] = mapped_column(String(2048))
