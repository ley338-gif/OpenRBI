import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.audit import SecurityEventResponse
from app.core.deps import require_role
from app.db.session import get_db
from app.models.security_event import SecurityEvent

router = APIRouter(
    prefix="/admin/security-events",
    tags=["admin"],
    dependencies=[Depends(require_role("ADMIN", "SECURITY_REVIEWER"))],
)

# Deliberately no PUT/DELETE anywhere in this router — that absence *is* the
# append-only enforcement at the API layer (docs/security-model.md#audit).
# The only way a SecurityEvent row is ever created is
# app/services/security_events.py's record_security_event; nothing in the
# codebase issues an UPDATE or DELETE against this table.


@router.get("", response_model=list[SecurityEventResponse])
async def list_security_events(
    event_type: str | None = None,
    user_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[SecurityEventResponse]:
    query = select(SecurityEvent).order_by(SecurityEvent.created_at.desc())
    if event_type:
        query = query.where(SecurityEvent.event_type == event_type)
    if user_id:
        query = query.where(SecurityEvent.user_id == user_id)
    if session_id:
        query = query.where(SecurityEvent.session_id == session_id)
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    return [SecurityEventResponse.from_model(e) for e in result.scalars()]
