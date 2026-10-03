"""Roadmap B2 follow-ups: the node poller keeps every approved, enrolled
node's telemetry current (not only the default node from .env), one
unreachable node doesn't hold up the others, /admin/health reports
enrolled nodes, and a revoked node is never silently swapped for the
default agent — its remaining sessions fail like those of a node that's
down.

Nodes are lightweight real HTTP servers standing in for a Session Agent
(test_scheduling.py's stubs), or an endpoint nothing listens on.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.config import get_settings
from app.core import node_poller, orphan_reconciler, session_agent_client
from app.core.crypto import encrypt_secret
from app.models.browser_node import BrowserNode
from app.models.browser_session import BrowserSession
from app.models.enums import BrowserNodeStatus, NodeEnrollmentStatus, SessionStatus
from app.models.security_event import SecurityEvent
from app.models.worker_metric_sample import WorkerMetricSample
from app.services.health import ComponentStatus, check_browser_nodes
from app.services.nodes import connection_for_node
from tests.conftest import make_user
from tests.integration.test_scheduling import _start_stub, _stop_stub, _StubAgent


async def _make_node(db, *, endpoint_url: str, enrollment=NodeEnrollmentStatus.APPROVED, token="stub-node-token") -> BrowserNode:
    node = BrowserNode(
        hostname=f"pytest-poll-{uuid.uuid4().hex[:8]}",
        status=BrowserNodeStatus.ONLINE,
        enrollment_status=enrollment,
        endpoint_url=endpoint_url,
        agent_token_encrypted=encrypt_secret(token) if token else None,
        capacity=10,
        active_sessions=0,
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return node


async def _delete_nodes(db, *node_ids: uuid.UUID) -> None:
    for node_id in node_ids:
        session_ids = (await db.execute(select(BrowserSession.id).where(BrowserSession.node_id == node_id))).scalars().all()
        if session_ids:
            await db.execute(delete(SecurityEvent).where(SecurityEvent.session_id.in_(session_ids)))
            await db.execute(delete(BrowserSession).where(BrowserSession.node_id == node_id))
        await db.execute(delete(WorkerMetricSample).where(WorkerMetricSample.node_id == node_id))
        await db.execute(delete(BrowserNode).where(BrowserNode.id == node_id))
    await db.commit()


@pytest.mark.asyncio
async def test_poll_once_refreshes_enrolled_nodes_and_tolerates_an_unreachable_one(db):
    stub = _StubAgent(f"pytest-poll-agent-{uuid.uuid4().hex[:8]}", capacity=7, active_sessions=3)
    server = await _start_stub(stub)
    live = await _make_node(db, endpoint_url=stub.base_url)
    down = await _make_node(db, endpoint_url="http://127.0.0.1:1")  # nothing listens here
    try:
        await node_poller.poll_once()

        await db.refresh(live)
        await db.refresh(down)
        assert live.last_heartbeat is not None
        assert live.active_sessions == 3
        assert live.capacity == 7
        assert down.last_heartbeat is None
        samples = (await db.execute(select(WorkerMetricSample).where(WorkerMetricSample.node_id == live.id))).scalars().all()
        assert len(samples) == 1
        assert samples[0].active_sessions == 3
    finally:
        await _stop_stub(server)
        await _delete_nodes(db, live.id, down.id)


@pytest.mark.asyncio
async def test_poll_once_skips_pending_and_revoked_nodes(db):
    stub = _StubAgent(f"pytest-poll-agent-{uuid.uuid4().hex[:8]}", capacity=7, active_sessions=3)
    server = await _start_stub(stub)
    pending = await _make_node(db, endpoint_url=stub.base_url, enrollment=NodeEnrollmentStatus.PENDING)
    revoked = await _make_node(db, endpoint_url=stub.base_url, enrollment=NodeEnrollmentStatus.REVOKED, token=None)
    try:
        await node_poller.poll_once()

        await db.refresh(pending)
        await db.refresh(revoked)
        assert pending.last_heartbeat is None
        assert revoked.last_heartbeat is None
    finally:
        await _stop_stub(server)
        await _delete_nodes(db, pending.id, revoked.id)


@pytest.mark.asyncio
async def test_revoked_node_is_never_routed_to_the_default_agent(db):
    revoked = await _make_node(db, endpoint_url="http://127.0.0.1:1", enrollment=NodeEnrollmentStatus.REVOKED, token=None)
    try:
        connection = connection_for_node(revoked)
        assert connection.base_url == "http://127.0.0.1:1"
        assert connection.base_url != get_settings().session_agent_base_url
        with pytest.raises(session_agent_client.SessionAgentError, match="revoked"):
            await session_agent_client.get_node_status(connection=connection)
    finally:
        await _delete_nodes(db, revoked.id)


@pytest.mark.asyncio
async def test_sessions_on_a_revoked_node_are_marked_failed(db):
    """A revoked node can't be reached any more (its token is gone), so its
    sessions must not stay ACTIVE forever — the reconciler treats them like
    sessions on a node that is down."""
    stub = _StubAgent(f"pytest-poll-agent-{uuid.uuid4().hex[:8]}", capacity=7, active_sessions=1)
    server = await _start_stub(stub)  # still answering: proves revocation, not reachability, decides
    revoked = await _make_node(db, endpoint_url=stub.base_url, enrollment=NodeEnrollmentStatus.REVOKED, token=None)
    owner, _ = await make_user(db, role_name="USER")
    session = BrowserSession(user_id=owner.id, node_id=revoked.id, status=SessionStatus.ACTIVE)
    db.add(session)
    await db.commit()
    orphan_reconciler._candidates.clear()
    orphan_reconciler._lost_candidates.clear()
    try:
        for _ in range(get_settings().orphan_reconcile_grace_cycles):
            await orphan_reconciler._reconcile_once()

        await db.refresh(session)
        assert session.status == SessionStatus.FAILED
    finally:
        await _stop_stub(server)
        await _delete_nodes(db, revoked.id)


@pytest.mark.asyncio
async def test_health_reports_an_offline_enrolled_node(db):
    stale = await _make_node(db, endpoint_url="http://127.0.0.1:1")
    stale.last_heartbeat = datetime.now(UTC) - timedelta(hours=1)
    await db.commit()
    try:
        component = await check_browser_nodes(db)
        assert component.name == "browser_nodes"
        assert component.status == ComponentStatus.DEGRADED
        assert f"{stale.hostname} OFFLINE" in component.detail

        stale.last_heartbeat = datetime.now(UTC)
        stale.cpu_percent = 1.0
        stale.ram_total_mb = 1024
        stale.ram_used_mb = 128
        await db.commit()
        component = await check_browser_nodes(db)
        assert stale.hostname not in (component.detail or "")
    finally:
        await _delete_nodes(db, stale.id)
