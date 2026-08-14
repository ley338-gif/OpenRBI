import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ClipboardMode, SessionStatus
from app.models.mixins import TimestampMixin, UUIDPKMixin


class BrowserSession(UUIDPKMixin, TimestampMixin, Base):
    """See docs/session-lifecycle.md for the full state machine. Resource
    limits are snapshotted at session creation so later config changes don't
    retroactively alter a running session's recorded limits.
    """

    __tablename__ = "browser_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("browser_nodes.id"), index=True
    )

    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="session_status"), nullable=False, default=SessionStatus.QUEUED
    )

    browser: Mapped[str] = mapped_column(String(64), nullable=False, default="firefox")
    sandbox_backend: Mapped[str] = mapped_column(String(64), nullable=False, default="docker")
    display_backend: Mapped[str] = mapped_column(String(64), nullable=False, default="novnc")

    cpu_limit: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=2.0)
    ram_limit_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    pid_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=512)
    disk_limit_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    screen_width: Mapped[int] = mapped_column(Integer, nullable=False, default=1280)
    screen_height: Mapped[int] = mapped_column(Integer, nullable=False, default=800)

    # Resolved once at session creation (resolve_clipboard_policy) and
    # snapshotted here, same pattern as screen_width/height — a later
    # policy edit never retroactively changes a running session's
    # enforcement (docs/policies.md).
    clipboard_mode: Mapped[ClipboardMode] = mapped_column(
        Enum(ClipboardMode, name="clipboard_mode"), nullable=False, default=ClipboardMode.BIDIRECTIONAL_TEXT
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
