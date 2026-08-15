"""RBI-POST-016 — an oversized download must be refused before its bytes
are ever fetched (nothing in app/services/downloads.py streams; fetching
means fully buffering in memory). Exercises the real
process_new_downloads() against a real DB session, with the Session
Agent HTTP calls monkeypatched — a live Docker sandbox isn't needed to
prove the size check happens before fetch_download() is ever called.
"""

import pytest
from sqlalchemy import select

from app.core import session_agent_client
from app.core.session_agent_client import DownloadedFile
from app.models.browser_session import BrowserSession
from app.models.enums import QuarantineStatus, ScannerStatus, SecurityEventType, SessionStatus
from app.models.security_event import SecurityEvent
from app.services.downloads import process_new_downloads
from tests.conftest import make_user


@pytest.mark.asyncio
async def test_oversized_download_is_quarantined_without_ever_being_fetched(db, monkeypatch):
    user, _ = await make_user(db)
    session = BrowserSession(user_id=user.id, status=SessionStatus.ACTIVE)
    db.add(session)
    await db.flush()

    from app.config import get_settings

    max_size = get_settings().download_max_size_bytes
    oversized_entry = DownloadedFile(filename="huge-file.bin", size_bytes=max_size + 1)

    async def fake_list_downloads(session_id: str):
        return [oversized_entry]

    async def fake_fetch_download(session_id: str, filename: str):
        raise AssertionError("fetch_download must never be called for an oversized file")

    deleted = []

    async def fake_delete_download(session_id: str, filename: str) -> None:
        deleted.append(filename)

    monkeypatch.setattr(session_agent_client, "list_downloads", fake_list_downloads)
    monkeypatch.setattr(session_agent_client, "fetch_download", fake_fetch_download)
    monkeypatch.setattr(session_agent_client, "delete_download", fake_delete_download)

    created = await process_new_downloads(db, session)

    assert len(created) == 1
    quarantine_file = created[0]
    assert quarantine_file.status == QuarantineStatus.QUARANTINED
    assert quarantine_file.scanner_status == ScannerStatus.ERROR
    assert quarantine_file.size_bytes == max_size + 1
    assert quarantine_file.storage_object_id is None  # never staged — never fetched
    assert "exceeds maximum allowed download size" in (quarantine_file.scanner_result or "")
    assert deleted == ["huge-file.bin"]

    result = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.quarantine_file_id == quarantine_file.id,
            SecurityEvent.event_type == SecurityEventType.DOWNLOAD_BLOCKED,
        )
    )
    event = result.scalars().first()
    assert event is not None
    assert event.metadata_json["reason"] == "exceeds maximum allowed download size"
