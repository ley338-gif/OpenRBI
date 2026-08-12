import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models.enums import IncidentSeverity, IncidentStatus, SecurityEventType
from app.models.incident import Incident
from app.models.security_event import SecurityEvent

# Project brief §21: "nicht jeder einzelne geblockte Download darf
# automatisch ein Incident werden" — a repeated pattern within a short
# window is what matters, not any single blocked transfer.
_REPEATED_VIOLATION_THRESHOLD = 3
_REPEATED_VIOLATION_WINDOW = timedelta(minutes=15)
_BLOCKED_EVENT_TYPES = (SecurityEventType.DOWNLOAD_BLOCKED, SecurityEventType.UPLOAD_BLOCKED)


async def check_repeated_policy_violations(db, user_id: uuid.UUID) -> None:
    """Called after recording a DOWNLOAD_BLOCKED/UPLOAD_BLOCKED event.
    Opens a REPEATED_POLICY_VIOLATION-style Incident once a user crosses
    the threshold within the window — but only one such incident stays
    open at a time per user; a user already under investigation for this
    doesn't get a fresh incident for every additional blocked transfer
    (same alert-fatigue avoidance the project brief calls for explicitly).
    """
    since = datetime.now(UTC) - _REPEATED_VIOLATION_WINDOW
    result = await db.execute(
        select(func.count())
        .select_from(SecurityEvent)
        .where(
            SecurityEvent.user_id == user_id,
            SecurityEvent.event_type.in_(_BLOCKED_EVENT_TYPES),
            SecurityEvent.created_at >= since,
        )
    )
    count = result.scalar_one()
    if count < _REPEATED_VIOLATION_THRESHOLD:
        return

    existing = await db.execute(
        select(Incident.id).where(
            Incident.user_id == user_id,
            Incident.title == "Repeated policy violations",
            Incident.status.in_((IncidentStatus.NEW, IncidentStatus.INVESTIGATING)),
        )
    )
    if existing.scalar_one_or_none() is not None:
        return

    db.add(
        Incident(
            severity=IncidentSeverity.HIGH,
            status=IncidentStatus.NEW,
            title="Repeated policy violations",
            description=(
                f"User had {count} blocked file transfers (download/upload) in the last "
                f"{int(_REPEATED_VIOLATION_WINDOW.total_seconds() // 60)} minutes."
            ),
            user_id=user_id,
        )
    )
    await db.flush()


async def update_incident(
    db,
    incident: Incident,
    *,
    status_value: IncidentStatus | None = None,
    assigned_to: uuid.UUID | None = None,
    resolution: str | None = None,
) -> None:
    if status_value is not None:
        incident.status = status_value
    if assigned_to is not None:
        incident.assigned_to = assigned_to
    if resolution is not None:
        incident.resolution = resolution
    db.add(incident)
    await db.flush()
