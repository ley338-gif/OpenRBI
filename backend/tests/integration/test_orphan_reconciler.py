"""Orphan-container reconciliation checklist items (docs/adr/0021), both
directions: a running container with no live BrowserSession row gets
terminated, and a BrowserSession row that should have a running container
but doesn't gets marked FAILED. Exercises the real Session Agent / Docker
socket, not a mock, and the real grace-period state in
app.core.orphan_reconciler.
"""

import pytest
from sqlalchemy import select, text

from app.core import orphan_reconciler, session_agent_client
from app.config import get_settings
from app.models.browser_session import BrowserSession
from app.models.enums import SecurityEventType, SessionStatus
from app.models.security_event import SecurityEvent
from app.services.sessions import create_session as create_session_service

from tests.conftest import make_user


async def _run_to_grace_period() -> None:
    settings = get_settings()
    for _ in range(settings.orphan_reconcile_grace_cycles):
        await orphan_reconciler._reconcile_once()


@pytest.mark.asyncio
async def test_orphaned_container_is_terminated_after_grace_period(db):
    """Regression check for the existing (container -> row) direction: a
    real container whose BrowserSession row was removed out from under it
    (raw DELETE, same shape as the historical test-cleanup bug docs/adr/0021
    was written for) is terminated once seen for
    orphan_reconcile_grace_cycles consecutive cycles.
    """
    owner, _ = await make_user(db, role_name="USER")
    session = await create_session_service(db, owner)
    await db.commit()
    session_id = session.id

    # Simulate the row disappearing without the container being torn down
    # via the real terminate path — same raw-DELETE shape as
    # tests/conftest.py's own cleanup fixture, the documented root cause.
    # security_events referencing the row must go first (FK), same ordering
    # conftest.py's own cleanup fixture uses.
    await db.execute(text("DELETE FROM security_events WHERE session_id = :id"), {"id": str(session_id)})
    await db.execute(text("DELETE FROM browser_sessions WHERE id = :id"), {"id": str(session_id)})
    await db.commit()

    orphan_reconciler._candidates.clear()
    orphan_reconciler._lost_candidates.clear()

    running_before = await session_agent_client.list_active_sandboxes()
    assert str(session_id) in running_before, "container should still be running before reconciliation"

    await _run_to_grace_period()

    running_after = await session_agent_client.list_active_sandboxes()
    assert str(session_id) not in running_after, "container should have been terminated"

    result = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.event_type == SecurityEventType.ORPHAN_SESSION_RECONCILED,
        ).order_by(SecurityEvent.created_at.desc())
    )
    events = [e for e in result.scalars() if e.metadata_json.get("session_id") == str(session_id)]
    assert events, "expected an ORPHAN_SESSION_RECONCILED event for this session"


@pytest.mark.asyncio
async def test_lost_session_row_is_marked_failed_after_grace_period(db):
    """New (row -> missing container) direction: an ACTIVE row whose
    container vanished without the DB being told (simulated here via a
    direct session_agent_client.terminate_sandbox() call, bypassing the
    normal terminate_session() service path entirely — the same effect a
    Docker/host restart has on a container with no restart policy) is
    marked FAILED with ended_at set, after the same grace period.
    """
    owner, _ = await make_user(db, role_name="USER")
    session = await create_session_service(db, owner)
    await db.commit()
    session_id = session.id
    assert session.status == SessionStatus.ACTIVE

    # Remove the container directly through the Session Agent, never
    # touching the BrowserSession row — simulates the container being gone
    # (host/Docker restart) while the DB still thinks it's ACTIVE.
    await session_agent_client.terminate_sandbox(str(session_id))

    running = await session_agent_client.list_active_sandboxes()
    assert str(session_id) not in running, "container should actually be gone"

    orphan_reconciler._candidates.clear()
    orphan_reconciler._lost_candidates.clear()

    await _run_to_grace_period()

    await db.refresh(session)
    assert session.status == SessionStatus.FAILED
    assert session.ended_at is not None

    result = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.event_type == SecurityEventType.SESSION_LOST_RECONCILED,
        ).order_by(SecurityEvent.created_at.desc())
    )
    events = [e for e in result.scalars() if e.session_id == session_id]
    assert events, "expected a SESSION_LOST_RECONCILED event for this session"
    assert events[0].metadata_json.get("last_status") == "ACTIVE"


@pytest.mark.asyncio
async def test_queued_session_without_container_is_not_marked_lost(db):
    """Counter-check: a QUEUED row with no container yet is the normal state
    during session creation, not evidence of anything lost — must never be
    marked FAILED by the new direction, grace period or not.
    """
    owner, _ = await make_user(db, role_name="USER")
    session = BrowserSession(user_id=owner.id, status=SessionStatus.QUEUED)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    session_id = session.id

    orphan_reconciler._candidates.clear()
    orphan_reconciler._lost_candidates.clear()

    await _run_to_grace_period()
    await _run_to_grace_period()  # extra cycle for margin

    await db.refresh(session)
    assert session.status == SessionStatus.QUEUED
    assert session.ended_at is None

    await db.execute(text("DELETE FROM browser_sessions WHERE id = :id"), {"id": str(session_id)})
    await db.commit()
