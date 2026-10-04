"""Unattended-session timeout (app/core/session_reaper.py): a session left
DISCONNECTED, or ACTIVE without a viewer, past
OPENRBI_SESSION_DISCONNECTED_TIMEOUT_SECONDS is terminated
through the real terminate_session() path (real Session Agent / Docker
container), while recently-disconnected and ISOLATED sessions are left
alone.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.api.display import reset_viewer_stamps
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


@pytest.mark.asyncio
async def test_active_session_nobody_ever_viewed_is_terminated(db, monkeypatch):
    """Started (ACTIVE once its display was ready), but the viewer never
    connected — e.g. the tab was closed while "Connecting display…". Before
    viewer_connected_at, such a sandbox ran until someone killed it.
    """
    owner, _ = await make_user(db, role_name="USER")
    session = await create_session_tolerating_transient_capacity(db, owner)
    assert session.status == SessionStatus.ACTIVE and session.viewer_connected_at is None
    session.last_activity_at = datetime.now(UTC) - timedelta(hours=2)
    await db.commit()
    session_id = session.id

    _use_timeout(monkeypatch, 3600.0)
    await session_reaper._reap_once()

    await db.refresh(session)
    assert session.status == SessionStatus.TERMINATED
    assert str(session_id) not in await session_agent_client.list_active_sandboxes()
    event = (
        await db.execute(
            select(SecurityEvent).where(
                SecurityEvent.event_type == SecurityEventType.SESSION_TIMED_OUT,
                SecurityEvent.session_id == session_id,
            )
        )
    ).scalars().first()
    assert event is not None and event.metadata_json["reason"] == "no_viewer_timeout"


@pytest.mark.asyncio
async def test_active_session_with_a_viewer_is_left_alone(db, monkeypatch):
    """Someone is looking at it: however long ago it started, it is not
    unattended (noVNC traffic can't tell idle from busy, so no idle timeout).
    """
    owner, _ = await make_user(db, role_name="USER")
    long_ago = datetime.now(UTC) - timedelta(days=2)
    session = BrowserSession(
        user_id=owner.id, status=SessionStatus.ACTIVE, last_activity_at=long_ago, viewer_connected_at=long_ago
    )
    db.add(session)
    await db.commit()

    _use_timeout(monkeypatch, 3600.0)
    await session_reaper._reap_once()

    await db.refresh(session)
    assert session.status == SessionStatus.ACTIVE

    session.status = SessionStatus.TERMINATED
    await db.commit()


@pytest.mark.asyncio
async def test_startup_reset_clears_stale_viewer_stamps_and_restarts_the_clock(db):
    """A crashed or killed backend never ran the per-connection cleanup; the
    process serving the display resets the stamps when it starts, and gives
    viewers a fresh timeout window to reconnect.
    """
    owner, _ = await make_user(db, role_name="USER")
    long_ago = datetime.now(UTC) - timedelta(days=2)
    stale = BrowserSession(
        user_id=owner.id, status=SessionStatus.ACTIVE, last_activity_at=long_ago, viewer_connected_at=long_ago
    )
    db.add(stale)
    await db.commit()

    assert await reset_viewer_stamps(db) >= 1

    await db.refresh(stale)
    assert stale.viewer_connected_at is None
    assert stale.last_activity_at > datetime.now(UTC) - timedelta(minutes=1)

    stale.status = SessionStatus.TERMINATED
    await db.commit()


def _use_stuck_timeout(monkeypatch, seconds: float) -> None:
    settings = get_settings().model_copy(update={"session_stuck_transition_timeout_seconds": seconds})
    monkeypatch.setattr(session_reaper, "get_settings", lambda: settings)


@pytest.mark.asyncio
async def test_session_stuck_terminating_is_torn_down(db, monkeypatch):
    """The window this recovery exists for: _reap_once() committed
    TERMINATING, then the backend died before terminate_session() finished,
    leaving the real container running under a TERMINATING row.
    """
    owner, _ = await make_user(db, role_name="USER")
    session = await create_session_tolerating_transient_capacity(db, owner)
    session.status = SessionStatus.TERMINATING
    session.updated_at = datetime.now(UTC) - timedelta(hours=1)
    await db.commit()
    session_id = session.id
    assert str(session_id) in await session_agent_client.list_active_sandboxes()

    _use_stuck_timeout(monkeypatch, 600.0)
    assert await session_reaper._recover_stuck_once() == 1

    await db.refresh(session)
    assert session.status == SessionStatus.TERMINATED
    assert str(session_id) not in await session_agent_client.list_active_sandboxes()

    result = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.event_type == SecurityEventType.SESSION_TIMED_OUT,
            SecurityEvent.session_id == session_id,
        )
    )
    event = result.scalars().first()
    assert event is not None, "expected a SESSION_TIMED_OUT event"
    assert event.metadata_json["reason"] == "stuck_terminating"


@pytest.mark.asyncio
async def test_session_stuck_starting_is_torn_down(db, monkeypatch):
    owner, _ = await make_user(db, role_name="USER")
    session = BrowserSession(user_id=owner.id, status=SessionStatus.STARTING)
    db.add(session)
    await db.flush()
    session.updated_at = datetime.now(UTC) - timedelta(hours=1)
    await db.commit()

    _use_stuck_timeout(monkeypatch, 600.0)
    assert await session_reaper._recover_stuck_once() == 1

    await db.refresh(session)
    assert session.status == SessionStatus.TERMINATED


@pytest.mark.asyncio
async def test_recent_transition_is_left_alone(db, monkeypatch):
    """A create or terminate that is still genuinely in flight must not be
    interfered with.
    """
    owner, _ = await make_user(db, role_name="USER")
    session = BrowserSession(user_id=owner.id, status=SessionStatus.TERMINATING)
    db.add(session)
    await db.commit()

    _use_stuck_timeout(monkeypatch, 600.0)
    assert await session_reaper._recover_stuck_once() == 0

    await db.refresh(session)
    assert session.status == SessionStatus.TERMINATING

    # Don't leave a live-looking row behind for other tests' global counts.
    session.status = SessionStatus.TERMINATED
    await db.commit()


@pytest.mark.asyncio
async def test_stuck_timeout_zero_disables_recovery(db, monkeypatch):
    owner, _ = await make_user(db, role_name="USER")
    session = BrowserSession(user_id=owner.id, status=SessionStatus.STARTING)
    db.add(session)
    await db.flush()
    session.updated_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()

    _use_stuck_timeout(monkeypatch, 0)
    assert await session_reaper._recover_stuck_once() == 0

    await db.refresh(session)
    assert session.status == SessionStatus.STARTING

    session.status = SessionStatus.TERMINATED
    await db.commit()
