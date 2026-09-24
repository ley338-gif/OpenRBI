"""DISCONNECTED-session timeout (app/core/session_reaper.py): a session left
DISCONNECTED past OPENRBI_SESSION_DISCONNECTED_TIMEOUT_SECONDS is terminated
through the real terminate_session() path (real Session Agent / Docker
container), while recently-disconnected and ISOLATED sessions are left
alone.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core import session_agent_client, session_reaper
from app.models.browser_session import BrowserSession
from app.models.enums import SecurityEventType, SessionStatus
from app.models.security_event import SecurityEvent

from tests.conftest import create_session_tolerating_transient_capacity, make_user


def _use_timeout(monkeypatch, seconds: float) -> None:
    settings = get_settings().model_copy(update={"session_disconnected_timeout_seconds": seconds})
    monkeypatch.setattr(session_reaper, "get_settings", lambda: settings)


@pytest.mark.asyncio
async def test_long_disconnected_session_is_terminated(db, monkeypatch):
    owner, _ = await make_user(db, role_name="USER")
    session = await create_session_tolerating_transient_capacity(db, owner)
    session.status = SessionStatus.DISCONNECTED
    session.last_activity_at = datetime.now(UTC) - timedelta(hours=2)
    await db.commit()
    session_id = session.id

    _use_timeout(monkeypatch, 3600.0)
    await session_reaper._reap_once()

    await db.refresh(session)
    assert session.status == SessionStatus.TERMINATED
    assert session.ended_at is not None
    assert str(session_id) not in await session_agent_client.list_active_sandboxes()

    result = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.event_type == SecurityEventType.SESSION_TIMED_OUT,
            SecurityEvent.session_id == session_id,
        )
    )
    event = result.scalars().first()
    assert event is not None, "expected a SESSION_TIMED_OUT event"
    assert event.metadata_json["reason"] == "disconnected_timeout"


@pytest.mark.asyncio
async def test_recently_disconnected_session_is_left_alone(db, monkeypatch):
    owner, _ = await make_user(db, role_name="USER")
    session = BrowserSession(
        user_id=owner.id, status=SessionStatus.DISCONNECTED, last_activity_at=datetime.now(UTC) - timedelta(minutes=5)
    )
    db.add(session)
    await db.commit()

    _use_timeout(monkeypatch, 3600.0)
    await session_reaper._reap_once()

    await db.refresh(session)
    assert session.status == SessionStatus.DISCONNECTED

    # Don't leave a live-looking row behind for other tests' global counts.
    session.status = SessionStatus.TERMINATED
    await db.commit()


@pytest.mark.asyncio
async def test_isolated_session_is_never_reaped(db, monkeypatch):
    """Isolation preserves the sandbox for investigation on purpose — age
    alone must never terminate it.
    """
    owner, _ = await make_user(db, role_name="USER")
    session = BrowserSession(
        user_id=owner.id, status=SessionStatus.ISOLATED, last_activity_at=datetime.now(UTC) - timedelta(days=30)
    )
    db.add(session)
    await db.commit()

    _use_timeout(monkeypatch, 60.0)
    await session_reaper._reap_once()

    await db.refresh(session)
    assert session.status == SessionStatus.ISOLATED

    # Don't leave a live-looking row behind for other tests' global counts.
    session.status = SessionStatus.TERMINATED
    await db.commit()


@pytest.mark.asyncio
async def test_timeout_zero_disables_reaping(db, monkeypatch):
    owner, _ = await make_user(db, role_name="USER")
    session = BrowserSession(
        user_id=owner.id, status=SessionStatus.DISCONNECTED, last_activity_at=datetime.now(UTC) - timedelta(days=30)
    )
    db.add(session)
    await db.commit()

    _use_timeout(monkeypatch, 0)
    assert await session_reaper._reap_once() == 0

    await db.refresh(session)
    assert session.status == SessionStatus.DISCONNECTED

    # Don't leave a live-looking row behind for other tests' global counts.
    session.status = SessionStatus.TERMINATED
    await db.commit()
