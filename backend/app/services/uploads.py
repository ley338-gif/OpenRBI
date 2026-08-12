import hashlib
import os

import magic

from app.core import session_agent_client
from app.core.clamav_client import ClamAVError, scan
from app.core.session_agent_client import SessionAgentError
from app.models.browser_session import BrowserSession
from app.models.enums import FileAction, IncidentSeverity, IncidentStatus, SecurityEventType
from app.models.incident import Incident
from app.services.incidents import check_repeated_policy_violations
from app.services.policy_engine import FileDecisionInput, evaluate_file_action
from app.services.security_events import record_security_event


class UploadBlockedError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


async def process_upload(db, session: BrowserSession, filename: str, data: bytes) -> None:
    """Project brief §17's pipeline: hash -> type detection -> scan ->
    policy -> temporary in-sandbox availability. No local directory is ever
    mounted into a sandbox (docs/security-model.md) — this is the only path
    bytes take to get in, and only after every check below passes.

    Unlike downloads, an upload has no deferred admin-review queue in MVP 1
    — the user is actively waiting on this action inside their live
    session, so QUARANTINE and DENY policy verdicts are both treated as an
    immediate block (project brief doesn't define an async upload-approval
    workflow; fail-closed favors blocking over silently queuing).
    """
    sha256 = hashlib.sha256(data).hexdigest()
    detected_mime = magic.from_buffer(data, mime=True)
    extension = os.path.splitext(filename)[1] or None

    decision = await evaluate_file_action(
        db,
        session.user_id,
        FileDecisionInput(detected_mime=detected_mime, extension=extension, size_bytes=len(data)),
    )

    if decision.action in (FileAction.DENY, FileAction.QUARANTINE):
        await record_security_event(
            db,
            SecurityEventType.UPLOAD_BLOCKED,
            user_id=session.user_id,
            session_id=session.id,
            metadata={"filename": filename, "sha256": sha256, "reason": f"policy {decision.action.value}"},
        )
        await check_repeated_policy_violations(db, session.user_id)
        await db.commit()
        raise UploadBlockedError(f"blocked by policy ({decision.action.value})")

    try:
        result = await scan(data)
    except ClamAVError:
        await record_security_event(
            db,
            SecurityEventType.UPLOAD_BLOCKED,
            user_id=session.user_id,
            session_id=session.id,
            metadata={"filename": filename, "sha256": sha256, "reason": "scanner unavailable — fail closed"},
        )
        await db.commit()
        raise UploadBlockedError("scanner unavailable")

    if result.infected:
        await record_security_event(
            db,
            SecurityEventType.MALWARE_DETECTED,
            user_id=session.user_id,
            session_id=session.id,
            metadata={"filename": filename, "sha256": sha256, "signature": result.signature, "direction": "upload"},
        )
        db.add(
            Incident(
                severity=IncidentSeverity.CRITICAL,
                status=IncidentStatus.NEW,
                title="Malware detected in uploaded file",
                description=(
                    f"ClamAV flagged upload '{filename}' (sha256={sha256}) as infected: {result.signature}."
                ),
                user_id=session.user_id,
                session_id=session.id,
            )
        )
        await db.commit()
        raise UploadBlockedError(f"infected: {result.signature}")

    try:
        await session_agent_client.write_upload(str(session.id), filename, data)
    except SessionAgentError as exc:
        raise UploadBlockedError(f"failed to place file in sandbox: {exc}") from exc

    await record_security_event(
        db,
        SecurityEventType.UPLOAD_REQUESTED,
        user_id=session.user_id,
        session_id=session.id,
        metadata={"filename": filename, "sha256": sha256, "detected_mime": detected_mime},
    )
    await db.commit()
