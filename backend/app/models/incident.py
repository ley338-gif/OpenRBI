import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import IncidentSeverity, IncidentStatus
from app.models.mixins import TimestampMixin, UUIDPKMixin


class Incident(UUIDPKMixin, TimestampMixin, Base):
    """Not every blocked action becomes its own incident — automatic
    creation is aggregated (e.g. repeated NETWORK_ACCESS_BLOCKED events) to
    avoid alert fatigue; see the project's incident rules.
    """

    __tablename__ = "incidents"

    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity, name="incident_severity"), nullable=False
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status"), nullable=False, default=IncidentStatus.NEW
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("browser_sessions.id"), index=True
    )
    quarantine_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quarantine_files.id")
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    resolution: Mapped[str | None] = mapped_column(Text)
