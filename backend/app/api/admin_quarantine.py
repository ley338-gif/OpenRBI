import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.quarantine import QuarantineFileResponse, ReviewRequest
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.quarantine import QuarantineFile
from app.models.user import User
from app.services.quarantine import QuarantineServiceError, reject_file, release_file

router = APIRouter(
    prefix="/admin/quarantine",
    tags=["admin"],
    dependencies=[Depends(require_role("ADMIN", "SECURITY_REVIEWER"))],
)


async def _get_or_404(db: AsyncSession, file_id: uuid.UUID) -> QuarantineFile:
    qf = await db.get(QuarantineFile, file_id)
    if qf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quarantine file not found")
    return qf


@router.get("", response_model=list[QuarantineFileResponse])
async def list_quarantine_files(
    status_filter: str | None = None, db: AsyncSession = Depends(get_db)
) -> list[QuarantineFileResponse]:
    """Never opens/previews the file itself (project brief §19: "Dateivorschau
    ist nicht Bestandteil von MVP 1") — only the metadata a reviewer needs:
    hash, source, MIME, scan status.
    """
    query = select(QuarantineFile).order_by(QuarantineFile.created_at.desc())
    if status_filter:
        query = query.where(QuarantineFile.status == status_filter)
    result = await db.execute(query)
    return [QuarantineFileResponse.from_model(qf) for qf in result.scalars()]


@router.get("/{file_id}", response_model=QuarantineFileResponse)
async def get_quarantine_file(file_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> QuarantineFileResponse:
    qf = await _get_or_404(db, file_id)
    return QuarantineFileResponse.from_model(qf)


@router.post("/{file_id}/release", response_model=QuarantineFileResponse)
async def release_quarantine_file(
    file_id: uuid.UUID,
    payload: ReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuarantineFileResponse:
    qf = await _get_or_404(db, file_id)
    try:
        await release_file(db, qf, reviewer_id=current_user.id, comment=payload.comment)
    except QuarantineServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return QuarantineFileResponse.from_model(qf)


@router.post("/{file_id}/reject", response_model=QuarantineFileResponse)
async def reject_quarantine_file(
    file_id: uuid.UUID,
    payload: ReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuarantineFileResponse:
    qf = await _get_or_404(db, file_id)
    try:
        await reject_file(db, qf, reviewer_id=current_user.id, comment=payload.comment)
    except QuarantineServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return QuarantineFileResponse.from_model(qf)
