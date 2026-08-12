import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.sessions import SessionResponse
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.browser_session import BrowserSession
from app.models.enums import SessionStatus
from app.models.user import User
from app.services.sessions import NoCapacityError, QuotaExceededError, SessionServiceError
from app.services.sessions import create_session as create_session_service
from app.services.sessions import terminate_session as terminate_session_service
from app.services.uploads import UploadBlockedError, process_upload

# Modest cap for MVP 1 — no chunked/resumable upload support yet, and this
# guards against a single request exhausting memory (the whole body is
# buffered before scanning). Revisit if real usage needs larger files.
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

router = APIRouter(prefix="/sessions", tags=["sessions"])


async def _get_own_session_or_404(db: AsyncSession, session_id: uuid.UUID, user: User) -> BrowserSession:
    """Fails closed: a session that exists but belongs to someone else
    returns 404, identically to a session that doesn't exist at all — never
    leaks whether the id is valid to a non-owner. Admin/reviewer access to
    other users' sessions is Phase 11 (a distinct, audited, role-gated path,
    not implicit here).
    """
    session = await db.get(BrowserSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return session


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def start_session(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SessionResponse:
    try:
        session = await create_session_service(db, current_user)
    except QuotaExceededError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except NoCapacityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except SessionServiceError as exc:
        await db.commit()  # keep the FAILED row (if any) for visibility rather than discarding it
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await db.commit()
    return SessionResponse.from_model(session)


@router.get("/me", response_model=list[SessionResponse])
async def list_my_sessions(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[SessionResponse]:
    result = await db.execute(
        select(BrowserSession)
        .where(BrowserSession.user_id == current_user.id)
        .order_by(BrowserSession.created_at.desc())
    )
    return [SessionResponse.from_model(s) for s in result.scalars()]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session_detail(
    session_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SessionResponse:
    session = await _get_own_session_or_404(db, session_id, current_user)
    return SessionResponse.from_model(session)


@router.post("/{session_id}/uploads", status_code=status.HTTP_201_CREATED)
async def upload_file(
    session_id: uuid.UUID,
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Project brief §17's Upload Gateway. No local directory is ever
    mounted into a sandbox — this is the only path a file takes to reach
    one, and only after hashing, type detection, a policy check, and a
    real scan all pass (app/services/uploads.py).
    """
    session = await _get_own_session_or_404(db, session_id, current_user)
    if session.status != SessionStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"session is not active ({session.status.value})")

    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="file too large")

    try:
        await process_upload(db, session, file.filename or "upload.bin", data)
    except UploadBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.reason) from exc

    return {"status": "ok"}


@router.post("/{session_id}/terminate", response_model=SessionResponse)
async def terminate_session(
    session_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SessionResponse:
    session = await _get_own_session_or_404(db, session_id, current_user)
    try:
        await terminate_session_service(db, session, actor_id=current_user.id)
    except SessionServiceError as exc:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    await db.commit()
    return SessionResponse.from_model(session)
