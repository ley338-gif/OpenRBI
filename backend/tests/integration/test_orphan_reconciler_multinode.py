"""Roadmap B2.5 (docs/roadmap-b2-multinode.md) — orphan reconciliation
walks every APPROVED node's own inventory, not one, and a node going
OFFLINE (unreachable) mid-session has documented, tested failure
behavior: no migration is attempted (sessions are sticky to their node,
Roadmap B2.3), the session transitions to FAILED once past the grace
period, and one unreachable node never blocks the reconciler from doing
its normal job on the others.

The "down" node here is a BrowserNode whose endpoint_url points at a port
nothing listens on (same technique as test_scheduling.py's unreachable-
node case) — every session_agent_client call against it fails exactly
like a real host that's actually gone, with no need to kill and restart
a real container to prove it.
"""

import uuid

import pytest
from sqlalchemy import delete, select

from app.config import get_settings
from app.core import orphan_reconciler
from app.core.crypto import encrypt_secret
from app.models.browser_node import BrowserNode
from app.models.browser_session import BrowserSession
from app.models.enums import BrowserNodeStatus, NodeEnrollmentStatus, SecurityEventType, SessionStatus
from app.models.security_event import SecurityEvent
from app.services.sessions import terminate_session

from tests.conftest import create_session_tolerating_transient_capacity, make_user


async def _make_unreachable_node(db) -> BrowserNode:
    node = BrowserNode(
        hostname=f"pytest-down-{uuid.uuid4().hex[:8]}",
        status=BrowserNodeStatus.ONLINE,
        enrollment_status=NodeEnrollmentStatus.APPROVED,
        endpoint_url="http://127.0.0.1:1",  # nothing listens here
        agent_token_encrypted=encrypt_secret("stub-node-token"),
        capacity=10,
        active_sessions=0,
    )
    db.add(node)
    await db.flush()
    return node


async def _delete_node_and_its_sessions(db, node_id: uuid.UUID) -> None:
    session_ids = (
        (await db.execute(select(BrowserSession.id).where(BrowserSession.node_id == node_id))).scalars().all()
    )
    if session_ids:
        await db.execute(delete(SecurityEvent).where(SecurityEvent.session_id.in_(session_ids)))
        await db.execute(delete(BrowserSession).where(BrowserSession.node_id == node_id))
    await db.execute(delete(BrowserNode).where(BrowserNode.id == node_id))
    await db.commit()


async def _run_to_grace_period() -> None:
    settings = get_settings()
    for _ in range(settings.orphan_reconcile_grace_cycles):
        await orphan_reconciler._reconcile_once()


@pytest.mark.asyncio
async def test_a_session_on_an_unreachable_node_is_marked_failed_after_grace_period(db):
    node = await _make_unreachable_node(db)
    owner, _ = await make_user(db, role_name="USER")
    session = BrowserSession(user_id=owner.id, node_id=node.id, status=SessionStatus.ACTIVE)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    session_id = session.id

    orphan_reconciler._candidates.clear()
    orphan_reconciler._lost_candidates.clear()

    try:
        await _run_to_grace_period()

        await db.refresh(session)
        assert session.status == SessionStatus.FAILED
        assert session.ended_at is not None

        result = await db.execute(
            select(SecurityEvent).where(
                SecurityEvent.event_type == SecurityEventType.SESSION_LOST_RECONCILED,
                SecurityEvent.session_id == session_id,
            )
        )
        event = result.scalars().first()
        assert event is not None
        # Distinguishes "node itself was unreachable" from the pre-existing
        # single-node case ("container specifically vanished, node fine").
        assert event.metadata_json.get("node_unreachable") is True
        assert event.metadata_json.get("node_id") == str(node.id)
    finally:
        await _delete_node_and_its_sessions(db, node.id)


@pytest.mark.asyncio
async def test_an_unreachable_node_does_not_block_reconciling_a_healthy_one(db):
    """One node being down must never stop the reconciler from doing its
    normal job on the others — proven by a real session on the real
    (reachable) default node staying untouched while a session on a
    simultaneously-down node is reconciled in the very same cycles.
    """
    down_node = await _make_unreachable_node(db)
    down_owner, _ = await make_user(db, role_name="USER")
    down_session = BrowserSession(user_id=down_owner.id, node_id=down_node.id, status=SessionStatus.ACTIVE)
    db.add(down_session)
    await db.commit()

    real_owner, _ = await make_user(db, role_name="USER")
    real_session = await create_session_tolerating_transient_capacity(db, real_owner)
    await db.commit()

    orphan_reconciler._candidates.clear()
    orphan_reconciler._lost_candidates.clear()

    try:
        await _run_to_grace_period()

        await db.refresh(down_session)
        assert down_session.status == SessionStatus.FAILED

        await db.refresh(real_session)
        assert real_session.status == SessionStatus.ACTIVE
    finally:
        await terminate_session(db, real_session, actor_id=real_owner.id)
        await db.commit()
        await _delete_node_and_its_sessions(db, down_node.id)
