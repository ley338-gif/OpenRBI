import uuid
from datetime import UTC, datetime

from app.models.enums import QuarantineStatus, SecurityEventType
from app.models.quarantine import QuarantineFile
from app.services.security_events import record_security_event


class QuarantineServiceError(ValueError):
    pass


async def release_file(
    db, quarantine_file: QuarantineFile, *, reviewer_id: uuid.UUID, comment: str
) -> None:
    """Manual admin/reviewer release (project brief §20). Only ever acts on
    a file still awaiting review — a file already RELEASED (e.g. via
    Phase 14's auto-release) or REJECTED is not re-releasable through this
    path, closing off any double-release or release-after-reject race.
    """
    if quarantine_file.status != QuarantineStatus.QUARANTINED:
        raise QuarantineServiceError(f"cannot release a file in status {quarantine_file.status.value}")

    quarantine_file.status = QuarantineStatus.RELEASED
    quarantine_file.reviewed_at = datetime.now(UTC)
    quarantine_file.reviewed_by = reviewer_id
    quarantine_file.review_comment = comment
    db.add(quarantine_file)

    await record_security_event(
        db,
        SecurityEventType.FILE_RELEASED,
        user_id=quarantine_file.user_id,
        session_id=quarantine_file.session_id,
        quarantine_file_id=quarantine_file.id,
        metadata={"reviewed_by": str(reviewer_id), "reason": "manual admin/reviewer release"},
    )
    await db.flush()


async def reject_file(
    db, quarantine_file: QuarantineFile, *, reviewer_id: uuid.UUID, comment: str
) -> None:
    if quarantine_file.status != QuarantineStatus.QUARANTINED:
        raise QuarantineServiceError(f"cannot reject a file in status {quarantine_file.status.value}")

    quarantine_file.status = QuarantineStatus.REJECTED
    quarantine_file.reviewed_at = datetime.now(UTC)
    quarantine_file.reviewed_by = reviewer_id
    quarantine_file.review_comment = comment
    db.add(quarantine_file)

    await record_security_event(
        db,
        SecurityEventType.FILE_REJECTED,
        user_id=quarantine_file.user_id,
        session_id=quarantine_file.session_id,
        quarantine_file_id=quarantine_file.id,
        metadata={"reviewed_by": str(reviewer_id)},
    )
    await db.flush()
