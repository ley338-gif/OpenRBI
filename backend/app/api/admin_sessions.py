import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.display import force_disconnect
from app.api.schemas.sessions import AdminSessionResponse
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.browser_session import BrowserSession
from app.models.user import User
from app.services.sessions import (
    SessionServiceError,
    disconnect_session,
    isolate_session,
    restore_session,
)
from app.services.sessions import terminate_session as terminate_session_service

router = APIRouter(
    prefix="/admin/sessions",
    tags=["admin"],
    dependencies=[Depends(require_role("ADMIN", "SECURITY_REVIEWER"))],
)


async def _to_response(db: AsyncSession, session: BrowserSession) -> AdminSessionResponse:
    user = await db.get(User, session.user_id)
    return AdminSessionResponse.from_model_with_user(session, user.username if user else "?")


async def _get_session_or_404(db: AsyncSession, session_id: uuid.UUID) -> BrowserSession:
    session = await db.get(BrowserSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return session


@router.get("", response_model=list[AdminSessionResponse])
async def list_sessions(db: AsyncSession = Depends(get_db)) -> list[AdminSessionResponse]:
    result = await db.execute(select(BrowserSession).order_by(BrowserSession.created_at.desc()))
    return [await _to_response(db, s) for s in result.scalars()]


@router.get("/{session_id}", response_model=AdminSessionResponse)
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> AdminSessionResponse:
    session = await _get_session_or_404(db, session_id)
    return await _to_response(db, session)


@router.post("/{session_id}/disconnect", response_model=AdminSessionResponse)
async def admin_disconnect(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminSessionResponse:
    session = await _get_session_or_404(db, session_id)
    try:
        await disconnect_session(db, session, actor_id=current_user.id)
    except SessionServiceError as exc:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    await force_disconnect(session_id)
    return await _to_response(db, session)


@router.post("/{session_id}/isolate", response_model=AdminSessionResponse)
async def admin_isolate(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminSessionResponse:
    session = await _get_session_or_404(db, session_id)
    try:
        await isolate_session(db, session, actor_id=current_user.id)
    except SessionServiceError as exc:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return await _to_response(db, session)


@router.post("/{session_id}/restore", response_model=AdminSessionResponse)
async def admin_restore(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminSessionResponse:
    session = await _get_session_or_404(db, session_id)
    try:
        await restore_session(db, session, actor_id=current_user.id)
    except SessionServiceError as exc:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return await _to_response(db, session)


@router.post(
    "/{session_id}/kill",
    response_model=AdminSessionResponse,
    dependencies=[Depends(require_role("ADMIN"))],
)
async def admin_kill(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminSessionResponse:
    """Restricted to ADMIN, not SECURITY_REVIEWER — the project brief lists
    Kill alongside Disconnect/Isolate for "User Detail Actions" without
    specifying which role, but §6 explicitly grants Isolate to
    SECURITY_REVIEWER and never mentions Kill for that role. Ambiguous ->
    the more restrictive reading (ADMIN-only) per the project's own stated
    principle for exactly this situation.
    """
    session = await _get_session_or_404(db, session_id)
    try:
        await terminate_session_service(db, session, actor_id=current_user.id)
    except SessionServiceError as exc:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    await db.commit()
    await force_disconnect(session_id)
    return await _to_response(db, session)
