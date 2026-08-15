"""V1 acceptance: manual quarantine release through the real admin API."""

import pytest
from sqlalchemy import func, select

from app.models.browser_session import BrowserSession
from app.models.enums import FileAction, QuarantineStatus, ScannerStatus, SecurityEventType, SessionStatus
from app.models.quarantine import QuarantineFile
from app.models.security_event import SecurityEvent
from tests.conftest import login, login_with_mfa_enrollment, make_user


async def make_quarantined_file(db, owner) -> QuarantineFile:
    session = BrowserSession(user_id=owner.id, status=SessionStatus.TERMINATED)
    db.add(session)
    await db.flush()
    item = QuarantineFile(
        session_id=session.id,
        user_id=owner.id,
        original_name="reviewed-report.pdf",
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        size_bytes=26,
        sha256="a" * 64,
        scanner_status=ScannerStatus.CLEAN,
        policy_action=FileAction.QUARANTINE,
        status=QuarantineStatus.QUARANTINED,
        storage_object_id="/app/data/staging/v1-manual-release-probe",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@pytest.mark.asyncio
async def test_security_reviewer_can_release_once_with_metadata_and_audit(db, client):
    owner, _ = await make_user(db, role_name="USER")
    reviewer, password = await make_user(db, role_name="SECURITY_REVIEWER")
    item = await make_quarantined_file(db, owner)
    cookie = await login_with_mfa_enrollment(client, reviewer.username, password)

    response = await client.post(
        f"/admin/quarantine/{item.id}/release",
        json={"comment": "Verified business document"},
        cookies={"openrbi_session": cookie},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "RELEASED"

    await db.refresh(item)
    assert item.reviewed_by == reviewer.id
    assert item.reviewed_at is not None
    assert item.review_comment == "Verified business document"
    event_count = await db.scalar(
        select(func.count(SecurityEvent.id)).where(
            SecurityEvent.quarantine_file_id == item.id,
            SecurityEvent.event_type == SecurityEventType.FILE_RELEASED,
        )
    )
    assert event_count == 1

    response = await client.post(
        f"/admin/quarantine/{item.id}/release",
        json={"comment": "release twice"},
        cookies={"openrbi_session": cookie},
    )
    assert response.status_code == 409
    assert "cannot release" in response.json()["detail"]


@pytest.mark.asyncio
async def test_normal_user_cannot_release_quarantine(db, client):
    owner, password = await make_user(db, role_name="USER")
    item = await make_quarantined_file(db, owner)
    cookie = await login(client, owner.username, password)

    response = await client.post(
        f"/admin/quarantine/{item.id}/release",
        json={"comment": "not authorized"},
        cookies={"openrbi_session": cookie},
    )
    assert response.status_code == 403
    await db.refresh(item)
    assert item.status == QuarantineStatus.QUARANTINED
