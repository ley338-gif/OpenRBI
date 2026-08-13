import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.display import force_disconnect
from app.api.schemas.sessions import (
    AdminSessionResponse,
    SessionListResponse,
    SessionOperationsStats,
)
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.browser_session import BrowserSession
from app.models.browser_node import BrowserNode
from app.models.enums import SessionStatus
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
    node = await db.get(BrowserNode, session.node_id) if session.node_id else None
    return AdminSessionResponse.from_model_with_user(
        session, user.username if user else "?", node.hostname if node else None
    )


async def _get_session_or_404(db: AsyncSession, session_id: uuid.UUID) -> BrowserSession:
    session = await db.get(BrowserSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return session


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    search: str | None = None,
    session_status: str | None = None,
    worker_id: uuid.UUID | None = None,
    since: datetime | None = None,
    sort_by: str = "started_at",
    sort_dir: str = "desc",
    offset: int = 0,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    if offset < 0 or limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="invalid pagination")
    filters = []
    if search:
        term = f"%{search.strip()}%"
        filters.append(or_(User.username.ilike(term), cast(BrowserSession.id, String).ilike(term)))
    if session_status:
        try:
            filters.append(BrowserSession.status == SessionStatus(session_status))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="unknown session status") from exc
    if worker_id:
        filters.append(BrowserSession.node_id == worker_id)
    if since:
        filters.append(BrowserSession.started_at >= since)

    base = (
        select(BrowserSession, User.username, BrowserNode.hostname)
        .join(User, User.id == BrowserSession.user_id)
        .outerjoin(BrowserNode, BrowserNode.id == BrowserSession.node_id)
        .where(*filters)
    )
    sort_columns = {
        "started_at": BrowserSession.started_at,
        "duration": func.coalesce(BrowserSession.ended_at, func.now()) - BrowserSession.started_at,
        "username": User.username,
        "status": BrowserSession.status,
    }
    sort_column = sort_columns.get(sort_by)
    if sort_column is None or sort_dir not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="invalid sort option")
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    ordering = (
        sort_column.desc().nulls_last()
        if sort_dir == "desc"
        else sort_column.asc().nulls_last()
    )
    rows = (await db.execute(base.order_by(ordering).offset(offset).limit(limit))).all()

    now = datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since_24h = now - timedelta(hours=24)
    active_statuses = (
        SessionStatus.QUEUED, SessionStatus.STARTING, SessionStatus.ACTIVE,
        SessionStatus.DISCONNECTED, SessionStatus.ISOLATING, SessionStatus.ISOLATED,
    )
    stats = (
        await db.execute(
            select(
                func.count(BrowserSession.id).filter(BrowserSession.status.in_(active_statuses)),
                func.count(BrowserSession.id).filter(BrowserSession.started_at >= today),
                func.avg(
                    func.extract("epoch", BrowserSession.ended_at - BrowserSession.started_at)
                ).filter(
                    BrowserSession.ended_at.is_not(None), BrowserSession.ended_at >= since_24h
                ),
                func.count(BrowserSession.id).filter(
                    BrowserSession.status == SessionStatus.FAILED,
                    BrowserSession.created_at >= since_24h,
                ),
                func.count(BrowserSession.id).filter(
                    BrowserSession.status == SessionStatus.TERMINATED,
                    BrowserSession.ended_at >= since_24h,
                ),
            )
        )
    ).one()
    return SessionListResponse(
        items=[
            AdminSessionResponse.from_model_with_user(session, username, hostname)
            for session, username, hostname in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
        stats=SessionOperationsStats(
            active=stats[0], sessions_today=stats[1],
            average_duration_seconds_24h=float(stats[2]) if stats[2] is not None else None,
            failed_24h=stats[3], terminated_24h=stats[4],
        ),
        statuses=[item.value for item in SessionStatus],
    )


@router.get("/{session_id}", response_model=AdminSessionResponse)
async def get_session(
    session_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> AdminSessionResponse:
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
