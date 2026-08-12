import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SecurityEventType
from app.models.security_event import SecurityEvent


async def record_security_event(
    db: AsyncSession,
    event_type: SecurityEventType,
    *,
    user_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    quarantine_file_id: uuid.UUID | None = None,
    metadata: dict | None = None,
) -> SecurityEvent:
    """Security events are append-only (docs/security-model.md#audit) — this
    is the only way application code should create them; never construct
    SecurityEvent rows ad hoc elsewhere. `metadata` must never contain
    passwords, MFA secrets, complete tokens, or file contents.
    """
    event = SecurityEvent(
        event_type=event_type,
        user_id=user_id,
        session_id=session_id,
        quarantine_file_id=quarantine_file_id,
        metadata_json=metadata,
    )
    db.add(event)
    await db.flush()
    return event
