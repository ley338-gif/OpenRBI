import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.quarantine import DownloadTokenResponse, QuarantineFileResponse
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
