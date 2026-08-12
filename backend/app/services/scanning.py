from app.core.clamav_client import ClamAVError, scan
from app.models.enums import (
    FileAction,
    IncidentSeverity,
    IncidentStatus,
    QuarantineStatus,
    ScannerStatus,
    SecurityEventType,
)
from app.models.incident import Incident
from app.models.quarantine import QuarantineFile
from app.services.security_events import record_security_event


async def scan_and_finalize(db, quarantine_file: QuarantineFile) -> None:
    """Runs the actual scan and applies the final status. Fail-closed at
    every branch (docs/adr/0008):
    - scanner error/unavailable -> QUARANTINED, never released, regardless
      of what the policy pre-check said;
    - infected -> QUARANTINED (kept for incident review, not silently
      deleted) plus a CRITICAL Incident (project brief §21's automatic-
      incident list includes MALWARE_DETECTED explicitly);
    - clean + policy DENY -> REJECTED immediately ("löschen/blockieren" —
      project brief §16 step 11 — no human review needed, policy already
      decided);
    - clean + policy QUARANTINE -> QUARANTINED, awaiting admin review
      (release/reject mechanics are Phase 15);
    - clean + policy AUTO_RELEASE -> RELEASED (the actual single-use
      download token for user retrieval is Phase 15 — this only marks the
      row as cleared).
    """
    quarantine_file.scanner_status = ScannerStatus.SCANNING
    db.add(quarantine_file)
    await db.flush()

    try:
        with open(quarantine_file.storage_object_id, "rb") as f:
            data = f.read()
        result = await scan(data)
    except (ClamAVError, OSError):
        quarantine_file.scanner_status = ScannerStatus.ERROR
        quarantine_file.status = QuarantineStatus.QUARANTINED
        db.add(quarantine_file)
        await record_security_event(
            db,
            SecurityEventType.DOWNLOAD_BLOCKED,
            user_id=quarantine_file.user_id,
            session_id=quarantine_file.session_id,
            quarantine_file_id=quarantine_file.id,
            metadata={"reason": "scanner unavailable — fail closed, no auto-release"},
        )
        await db.flush()
        return

    if result.infected:
        quarantine_file.scanner_status = ScannerStatus.INFECTED
        quarantine_file.scanner_result = result.signature
        quarantine_file.status = QuarantineStatus.QUARANTINED
        db.add(quarantine_file)
        await record_security_event(
            db,
            SecurityEventType.MALWARE_DETECTED,
            user_id=quarantine_file.user_id,
            session_id=quarantine_file.session_id,
            quarantine_file_id=quarantine_file.id,
            metadata={"signature": result.signature},
        )
        db.add(
            Incident(
                severity=IncidentSeverity.CRITICAL,
                status=IncidentStatus.NEW,
                title="Malware detected in downloaded file",
                description=(
                    f"ClamAV flagged '{quarantine_file.original_name}' "
                    f"(sha256={quarantine_file.sha256}) as infected: {result.signature}."
                ),
                user_id=quarantine_file.user_id,
                session_id=quarantine_file.session_id,
                quarantine_file_id=quarantine_file.id,
            )
        )
        await db.flush()
        return

    quarantine_file.scanner_status = ScannerStatus.CLEAN
    db.add(quarantine_file)

    if quarantine_file.policy_action == FileAction.DENY:
        quarantine_file.status = QuarantineStatus.REJECTED
        db.add(quarantine_file)
        await record_security_event(
            db,
            SecurityEventType.DOWNLOAD_BLOCKED,
            user_id=quarantine_file.user_id,
            session_id=quarantine_file.session_id,
            quarantine_file_id=quarantine_file.id,
            metadata={"reason": "policy DENY"},
        )
    elif quarantine_file.policy_action == FileAction.AUTO_RELEASE:
        quarantine_file.status = QuarantineStatus.RELEASED
        db.add(quarantine_file)
        await record_security_event(
            db,
            SecurityEventType.FILE_RELEASED,
            user_id=quarantine_file.user_id,
            session_id=quarantine_file.session_id,
            quarantine_file_id=quarantine_file.id,
            metadata={"reason": "policy AUTO_RELEASE, scan clean"},
        )
    else:  # QUARANTINE, or no policy matched (fail-closed default)
        quarantine_file.status = QuarantineStatus.QUARANTINED
        db.add(quarantine_file)
        await record_security_event(
            db,
            SecurityEventType.FILE_QUARANTINED,
            user_id=quarantine_file.user_id,
            session_id=quarantine_file.session_id,
            quarantine_file_id=quarantine_file.id,
        )

    await db.flush()
