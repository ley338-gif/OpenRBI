"""Downloads/quarantine retention — periodically deletes the staged bytes
(and scrubs descriptive metadata) of QuarantineFile rows once their
retention window has passed. Same in-process-task pattern as
app/core/node_poller.py/download_poller.py/orphan_reconciler.py.

Before this job existed, nothing ever deleted a QuarantineFile row or its
staged bytes (app/services/quarantine.py only has release_file()/
reject_file(), neither of which touches storage) — every downloaded file
(released, quarantined, or rejected) stayed on disk and in the database
forever. That's both a storage-growth and a data-minimization/compliance
issue (original_name, source_host, and URLs kept indefinitely for files
users have already retrieved or that were rejected long ago).

Two separate windows (docs/adr/0022):
- RELEASED files: short-lived (default 24h) — cheap to re-request (a
  fresh 5-minute release token) and carry no forensic value once
  delivered.
- QUARANTINED/REJECTED files: long-lived (default 90 days) — retain
  incident-review value.

A file still referenced by an open Incident (NEW/INVESTIGATING) is never
touched regardless of age — see _has_open_incident().

The row itself is never hard-deleted: it transitions to the existing
QuarantineStatus.DELETED terminal state (already wired into
app/api/files.py's "deleted" filter group and documented in
docs/quarantine.md's state machine) with storage_object_id cleared and
descriptive fields scrubbed, not removed from the table outright — so
file-history/statistics views keep working, and the audit trail (this
job's own QUARANTINE_FILE_RETENTION_EXPIRED event) has a stable id to
reference.

`storage_object_id` is content-addressed by SHA-256 (app/services/
downloads.py's _stage_file) — the same bytes on disk can legitimately be
referenced by more than one QuarantineFile row (e.g. two different users
downloading the same file). The bytes are only actually removed once no
other, still-live row references the same hash.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.db.session import async_session_factory
from app.models.enums import IncidentStatus, QuarantineStatus, SecurityEventType
from app.models.incident import Incident
from app.models.quarantine import QuarantineFile
from app.services.security_events import record_security_event

logger = logging.getLogger("openrbi.quarantine_retention")

_OPEN_INCIDENT_STATUSES = (IncidentStatus.NEW, IncidentStatus.INVESTIGATING)

_SCRUBBED_NAME = "[retention-expired]"

_task = None


def _effective_status_at(qf: QuarantineFile) -> datetime:
    """The timestamp the retention window is actually measured from: when
    the file was reviewed (release_file()/reject_file(), or scan_and_
    finalize()'s auto-release/auto-reject path — the latter never sets
    reviewed_at, since it happens synchronously in the same call as
    quarantine_file creation), falling back to created_at when there was
    no separate review step.
    """
    return qf.reviewed_at or qf.created_at


async def _has_open_incident(db, quarantine_file_id) -> bool:
    result = await db.execute(
        select(Incident.id).where(
            Incident.quarantine_file_id == quarantine_file_id,
            Incident.status.in_(_OPEN_INCIDENT_STATUSES),
        )
    )
    return result.first() is not None


async def _other_live_rows_share_hash(db, sha256: str, exclude_id) -> bool:
    result = await db.execute(
        select(QuarantineFile.id).where(
            QuarantineFile.sha256 == sha256,
            QuarantineFile.id != exclude_id,
            QuarantineFile.status != QuarantineStatus.DELETED,
        )
    )
    return result.first() is not None


async def _delete_one(db, qf: QuarantineFile) -> None:
    if await _has_open_incident(db, qf.id):
        return

    storage_object_id = qf.storage_object_id
    if storage_object_id and not await _other_live_rows_share_hash(db, qf.sha256, qf.id):
        try:
            os.remove(storage_object_id)
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("failed to remove staged file %s for quarantine file %s", storage_object_id, qf.id)
            # Don't flip the row to DELETED if the bytes are still on disk
            # and we couldn't remove them — fail closed, retry next cycle.
            return

    await record_security_event(
        db,
        SecurityEventType.QUARANTINE_FILE_RETENTION_EXPIRED,
        user_id=qf.user_id,
        session_id=qf.session_id,
        quarantine_file_id=qf.id,
        metadata={
            "original_name": qf.original_name,
            "sha256": qf.sha256,
            "previous_status": qf.status.value,
            "expired_at": datetime.now(UTC).isoformat(),
        },
    )

    qf.status = QuarantineStatus.DELETED
    qf.storage_object_id = None
    qf.original_name = _SCRUBBED_NAME
    qf.source_host = None
    qf.initial_url = None
    qf.final_url = None
    qf.redirect_chain = None
    db.add(qf)


async def _reconcile_once() -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    released_cutoff = now - timedelta(hours=settings.quarantine_retention_released_hours)
    quarantined_cutoff = now - timedelta(days=settings.quarantine_retention_quarantined_days)

    async with async_session_factory() as db:
        result = await db.execute(
            select(QuarantineFile).where(
                QuarantineFile.status.in_(
                    (QuarantineStatus.RELEASED, QuarantineStatus.QUARANTINED, QuarantineStatus.REJECTED)
                )
            )
        )
        candidates = list(result.scalars())

        expired = [
            qf
            for qf in candidates
            if (
                qf.status == QuarantineStatus.RELEASED
                and _effective_status_at(qf) < released_cutoff
            )
            or (
                qf.status in (QuarantineStatus.QUARANTINED, QuarantineStatus.REJECTED)
                and _effective_status_at(qf) < quarantined_cutoff
            )
        ]

        for qf in expired:
            await _delete_one(db, qf)

        if expired:
            await db.commit()


async def _poll_loop() -> None:
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.quarantine_retention_interval_seconds)
        try:
            await _reconcile_once()
        except Exception:
            logger.exception("quarantine retention cycle failed unexpectedly")


def start() -> None:
    global _task
    if _task is not None:
        return
    _task = asyncio.create_task(_poll_loop())


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
