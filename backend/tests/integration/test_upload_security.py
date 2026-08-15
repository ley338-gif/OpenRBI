import hashlib

import pytest
from sqlalchemy import select

from app.core.clamav_client import ClamAVError, ScanResult
from app.models.browser_session import BrowserSession
from app.models.enums import FileAction, SecurityEventType, SessionStatus
from app.models.incident import Incident
from app.models.security_event import SecurityEvent
from app.services import uploads
from app.services.policy_engine import FileDecisionResult
from app.services.uploads import UploadBlockedError, process_upload
from tests.conftest import make_user


def _allow_result() -> FileDecisionResult:
    return FileDecisionResult(
        action=FileAction.AUTO_RELEASE,
        policy_version_id=None,
        matched_rule_id=None,
        reason="security review fixture",
    )


async def _session(db):
    user, _ = await make_user(db, role_name="USER")
    session = BrowserSession(user_id=user.id, status=SessionStatus.ACTIVE)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@pytest.mark.asyncio
async def test_clean_upload_is_hashed_scanned_and_written(db, monkeypatch):
    session = await _session(db)
    payload = b"benign upload security review\n"
    written = {}

    async def allow(*_args, **_kwargs):
        return _allow_result()

    async def clean(_data):
        return ScanResult(infected=False, signature=None)

    async def write(session_id, filename, data):
        written.update(session_id=session_id, filename=filename, data=data)

    monkeypatch.setattr(uploads, "evaluate_file_action", allow)
    monkeypatch.setattr(uploads, "scan", clean)
    monkeypatch.setattr(uploads.session_agent_client, "write_upload", write)

    await process_upload(db, session, "report.txt", payload)
    assert written == {"session_id": str(session.id), "filename": "report.txt", "data": payload}
    event = await db.scalar(
        select(SecurityEvent).where(
            SecurityEvent.session_id == session.id,
            SecurityEvent.event_type == SecurityEventType.UPLOAD_REQUESTED,
        )
    )
    assert event is not None
    assert event.metadata_json["sha256"] == hashlib.sha256(payload).hexdigest()
    assert event.metadata_json["detected_mime"] == "text/plain"


@pytest.mark.asyncio
async def test_scanner_outage_blocks_upload_before_sandbox_write(db, monkeypatch):
    session = await _session(db)
    wrote = False

    async def allow(*_args, **_kwargs):
        return _allow_result()

    async def unavailable(_data):
        raise ClamAVError("review outage")

    async def write(*_args, **_kwargs):
        nonlocal wrote
        wrote = True

    monkeypatch.setattr(uploads, "evaluate_file_action", allow)
    monkeypatch.setattr(uploads, "scan", unavailable)
    monkeypatch.setattr(uploads.session_agent_client, "write_upload", write)

    with pytest.raises(UploadBlockedError, match="scanner unavailable"):
        await process_upload(db, session, "report.txt", b"unscanned bytes")
    assert wrote is False
    event = await db.scalar(
        select(SecurityEvent).where(
            SecurityEvent.session_id == session.id,
            SecurityEvent.event_type == SecurityEventType.UPLOAD_BLOCKED,
        )
    )
    assert event is not None
    assert event.metadata_json["reason"] == "scanner unavailable — fail closed"


@pytest.mark.asyncio
async def test_malicious_upload_creates_incident_and_never_reaches_sandbox(db, monkeypatch):
    session = await _session(db)
    wrote = False

    async def allow(*_args, **_kwargs):
        return _allow_result()

    async def infected(_data):
        return ScanResult(infected=True, signature="Eicar-Signature")

    async def write(*_args, **_kwargs):
        nonlocal wrote
        wrote = True

    monkeypatch.setattr(uploads, "evaluate_file_action", allow)
    monkeypatch.setattr(uploads, "scan", infected)
    monkeypatch.setattr(uploads.session_agent_client, "write_upload", write)

    with pytest.raises(UploadBlockedError, match="infected: Eicar-Signature"):
        await process_upload(db, session, "eicar.com", b"malicious fixture")
    assert wrote is False
    assert await db.scalar(
        select(SecurityEvent).where(
            SecurityEvent.session_id == session.id,
            SecurityEvent.event_type == SecurityEventType.MALWARE_DETECTED,
        )
    ) is not None
    assert await db.scalar(select(Incident).where(Incident.session_id == session.id)) is not None
