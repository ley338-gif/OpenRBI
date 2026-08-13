import os
import uuid
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.quarantine import DownloadTokenResponse, QuarantineFileResponse, UserFilePage, UserFileSummary
from app.core.deps import get_current_user
from app.core.release_tokens import consume_token, create_token
from app.db.session import get_db
from app.models.enums import QuarantineStatus
from app.models.quarantine import QuarantineFile
from app.models.user import User

router = APIRouter(prefix="/files", tags=["files"])

_TOKEN_TTL_SECONDS = 5 * 60


async def _get_own_file_or_404(db: AsyncSession, file_id: uuid.UUID, user: User) -> QuarantineFile:
    """Same ownership pattern as sessions/display (app/api/sessions.py,
    app/api/display.py): a file belonging to someone else is
    indistinguishable from a nonexistent one.
    """
    qf = await db.get(QuarantineFile, file_id)
    if qf is None or qf.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    return qf


@router.get("/me", response_model=list[QuarantineFileResponse])
async def list_my_files(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[QuarantineFileResponse]:
    result = await db.execute(
        select(QuarantineFile)
        .where(QuarantineFile.user_id == current_user.id)
        .order_by(QuarantineFile.created_at.desc())
    )
    return [QuarantineFileResponse.from_model(qf) for qf in result.scalars()]


@router.get("/me/page", response_model=UserFilePage)
async def list_my_files_page(
    status_filter: str | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserFilePage:
    """Paginated user-owned file history. Filters are applied in SQL; the
    ownership predicate is mandatory and never supplied by the caller.
    """
    owned = [QuarantineFile.user_id == current_user.id]
    filtered = list(owned)
    status_groups = {
        "pending": (QuarantineStatus.PENDING_SCAN, QuarantineStatus.SCANNING, QuarantineStatus.QUARANTINED),
        "approved": (QuarantineStatus.RELEASED,),
        "blocked": (QuarantineStatus.REJECTED,),
        "deleted": (QuarantineStatus.DELETED,),
    }
    if status_filter and status_filter != "all":
        states = status_groups.get(status_filter.lower())
        if states is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unknown file status filter")
        filtered.append(QuarantineFile.status.in_(states))
    if search:
        term = f"%{search.strip()}%"
        filtered.append(or_(QuarantineFile.original_name.ilike(term), QuarantineFile.detected_mime.ilike(term)))
    if date_from:
        filtered.append(QuarantineFile.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        filtered.append(QuarantineFile.created_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc))

    total_filtered = (await db.execute(select(func.count()).select_from(QuarantineFile).where(*filtered))).scalar_one()
    rows = await db.execute(
        select(QuarantineFile).where(*filtered).order_by(QuarantineFile.created_at.desc()).offset(offset).limit(limit)
    )

    async def count_states(states: tuple[QuarantineStatus, ...] | None = None) -> int:
        query = select(func.count()).select_from(QuarantineFile).where(*owned)
        if states is not None:
            query = query.where(QuarantineFile.status.in_(states))
        return (await db.execute(query)).scalar_one()

    summary = UserFileSummary(
        total=await count_states(),
        pending=await count_states(status_groups["pending"]),
        approved=await count_states(status_groups["approved"]),
        blocked=await count_states(status_groups["blocked"]),
    )
    return UserFilePage(
        items=[QuarantineFileResponse.from_model(qf) for qf in rows.scalars()],
        summary=summary, total_filtered=total_filtered, offset=offset, limit=limit,
    )


@router.post("/{file_id}/download-token", response_model=DownloadTokenResponse)
async def request_download_token(
    file_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DownloadTokenResponse:
    qf = await _get_own_file_or_404(db, file_id, current_user)
    if qf.status != QuarantineStatus.RELEASED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"file is not released (status={qf.status.value})")
    token = await create_token(qf.id, current_user.id)
    return DownloadTokenResponse(token=token, expires_in_seconds=_TOKEN_TTL_SECONDS)


@router.get("/download/{token}")
async def download_with_token(
    token: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> FileResponse:
    """Fails closed on every axis (project brief §20): an unknown/expired/
    already-used token is a 401 indistinguishable from a forged one
    (consume_token already deleted it atomically); a token whose user
    doesn't match the current session is also a 401, not a 403 —never
    confirm to a caller that a *valid* token exists for someone else.
    """
    claim = await consume_token(token)
    if claim is None or claim["user_id"] != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired download token")

    qf = await db.get(QuarantineFile, uuid.UUID(claim["quarantine_file_id"]))
    if qf is None or qf.status != QuarantineStatus.RELEASED or not qf.storage_object_id:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="file no longer available")
    if not os.path.exists(qf.storage_object_id):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="file no longer available")

    return FileResponse(
        qf.storage_object_id,
        media_type="application/octet-stream",
        filename=qf.original_name,
    )
