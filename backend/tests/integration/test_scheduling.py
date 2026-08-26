"""Roadmap B2.3 (docs/roadmap-b2-multinode.md) — select_node() stops being
a single-node stub and does real cross-node selection: query every
APPROVED node, refresh each from its own agent, pick the least-loaded
ONLINE node with free capacity, break ties deterministically by hostname,
and fail closed with NoCapacityError only when literally none are usable.

As in test_node_routing.py, the "nodes" here are lightweight real HTTP
servers (uvicorn + Starlette) standing in for a second/third Session
Agent — not full Docker-backed agents. This phase is about scheduling
logic, not sandbox lifecycle (already covered elsewhere), so a real HTTP
self-report endpoint with a controllable capacity/active_sessions body is
everything the test needs.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
import uvicorn
from sqlalchemy import delete, select as sa_select
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core.crypto import encrypt_secret
from app.models.browser_node import BrowserNode
from app.models.enums import BrowserNodeStatus, NodeEnrollmentStatus
from app.services.sessions import NoCapacityError, select_node


class _StubAgent:
    def __init__(self, hostname: str, *, capacity: int, active_sessions: int):
        self.hostname = hostname
        self.capacity = capacity
        self.active_sessions = active_sessions

    async def self_report(self, request):
        return JSONResponse(
            {
                "hostname": self.hostname,
                "status": "ONLINE",
                "capacity": self.capacity,
                "active_sessions": self.active_sessions,
                "runtime": "docker",
                "version": "test",
                "sandbox_image_available": True,
                "cpu_percent": 1.0,
                "ram_total_mb": 1024,
                "ram_used_mb": 128,
                "node_started_at": datetime.now(UTC).isoformat(),
            }
        )


async def _start_stub(stub: _StubAgent) -> uvicorn.Server:
    app = Starlette(routes=[Route("/v1/nodes/self", stub.self_report, methods=["GET"])])
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    stub.base_url = f"http://127.0.0.1:{port}"
    server._openrbi_task = server_task  # keep a reference so it isn't GC'd
    return server


async def _stop_stub(server: uvicorn.Server) -> None:
    server.should_exit = True
    await server._openrbi_task


@pytest_asyncio.fixture
async def only_our_nodes_are_candidates(db):
    """select_node() considers every APPROVED node in the DB, including
    whatever pre-existing default node the shared dev/CI docker-compose
    stack already auto-registered from earlier tests. Temporarily parking
    every pre-existing APPROVED node in MAINTENANCE isolates these
    scheduling-logic tests to just the stub nodes each test creates,
    without touching (deleting/reusing) the real shared row other tests
    depend on. Restored unconditionally afterwards.
    """
    result = await db.execute(
        sa_select(BrowserNode).where(BrowserNode.enrollment_status == NodeEnrollmentStatus.APPROVED)
    )
    pre_existing = list(result.scalars().all())
    original_statuses = {node.id: node.status for node in pre_existing}
    for node in pre_existing:
        node.status = BrowserNodeStatus.MAINTENANCE
    await db.commit()
    try:
        yield
    finally:
        for node_id, status in original_statuses.items():
            node = await db.get(BrowserNode, node_id)
            if node is not None:
                node.status = status
        await db.commit()


@pytest_asyncio.fixture
async def two_stub_agents():
    a = _StubAgent(f"pytest-sched-a-{uuid.uuid4().hex[:8]}", capacity=10, active_sessions=8)
    b = _StubAgent(f"pytest-sched-b-{uuid.uuid4().hex[:8]}", capacity=10, active_sessions=2)
    server_a = await _start_stub(a)
    server_b = await _start_stub(b)
    yield a, b
    await _stop_stub(server_a)
    await _stop_stub(server_b)


async def _make_approved_node(db, stub: _StubAgent) -> BrowserNode:
    node = BrowserNode(
        hostname=stub.hostname,
        status=BrowserNodeStatus.ONLINE,
        enrollment_status=NodeEnrollmentStatus.APPROVED,
        endpoint_url=stub.base_url,
        agent_token_encrypted=encrypt_secret("stub-node-token"),
        capacity=stub.capacity,
        active_sessions=stub.active_sessions,
    )
    db.add(node)
    await db.flush()
    return node


async def _delete_node(db, node_id: uuid.UUID) -> None:
    await db.execute(delete(BrowserNode).where(BrowserNode.id == node_id))
    await db.commit()


@pytest.mark.asyncio
async def test_select_node_picks_the_least_loaded_of_multiple_approved_nodes(db, only_our_nodes_are_candidates, two_stub_agents):
    stub_a, stub_b = two_stub_agents  # a: 8/10 free=2, b: 2/10 free=8
    node_a = await _make_approved_node(db, stub_a)
    node_b = await _make_approved_node(db, stub_b)
    await db.commit()

    try:
        chosen = await select_node(db)
        assert chosen.hostname == stub_b.hostname
        # select_node() also refreshed both rows' telemetry from their own
        # agent's live self-report, not just picked blindly.
        assert chosen.active_sessions == 2
    finally:
        await _delete_node(db, node_a.id)
        await _delete_node(db, node_b.id)


@pytest.mark.asyncio
async def test_select_node_breaks_a_free_capacity_tie_by_lowest_hostname(db, only_our_nodes_are_candidates, two_stub_agents):
    stub_a, stub_b = two_stub_agents
    stub_a.active_sessions = 5
    stub_b.active_sessions = 5  # identical free capacity now
    expected = min(stub_a.hostname, stub_b.hostname)

    node_a = await _make_approved_node(db, stub_a)
    node_b = await _make_approved_node(db, stub_b)
    await db.commit()

    try:
        chosen = await select_node(db)
        assert chosen.hostname == expected
    finally:
        await _delete_node(db, node_a.id)
        await _delete_node(db, node_b.id)


@pytest.mark.asyncio
async def test_select_node_fails_closed_when_every_approved_node_is_full(db, only_our_nodes_are_candidates, two_stub_agents):
    stub_a, stub_b = two_stub_agents
    stub_a.active_sessions = stub_a.capacity
    stub_b.active_sessions = stub_b.capacity

    node_a = await _make_approved_node(db, stub_a)
    node_b = await _make_approved_node(db, stub_b)
    await db.commit()

    try:
        with pytest.raises(NoCapacityError):
            await select_node(db)
    finally:
        await _delete_node(db, node_a.id)
        await _delete_node(db, node_b.id)


@pytest.mark.asyncio
async def test_select_node_skips_an_unreachable_node_and_still_schedules_the_other(db, only_our_nodes_are_candidates, two_stub_agents):
    stub_a, stub_b = two_stub_agents
    node_a = await _make_approved_node(db, stub_a)
    node_b = await _make_approved_node(db, stub_b)
    # Point node_a at a port nothing is listening on — simulates a node
    # whose agent is down without needing to actually kill the server.
    node_a.endpoint_url = "http://127.0.0.1:1"
    await db.commit()

    try:
        chosen = await select_node(db)
        assert chosen.hostname == stub_b.hostname
    finally:
        await _delete_node(db, node_a.id)
        await _delete_node(db, node_b.id)
