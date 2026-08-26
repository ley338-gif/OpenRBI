"""Roadmap B2.2 (docs/roadmap-b2-multinode.md) — every session-lifecycle
call in app/core/session_agent_client.py now accepts a per-node
`connection` (base_url/token), resolved via app/services/nodes.py's
connection_for_node(). This verifies that resolution actually routes a
session's isolate/restore/terminate calls to the specific node it lives
on, not the single default agent, and that a node with no endpoint_url
(the pre-B2.1/legacy case) still falls back to the old settings-based
behavior unchanged.

The "second node" here is a lightweight real HTTP server (uvicorn +
Starlette), not the full Session Agent image — it doesn't touch Docker at
all. That's a deliberate scope choice: this test verifies *routing*
(did the request reach the right base_url, with the right per-node
token), which the existing single-node integration suite already
verifies works end-to-end against the real Session Agent/Docker for the
default node. Spinning up a second real Docker-backed agent for a
routing-only check would test the same sandbox-lifecycle code path
twice for no additional coverage.
"""

import asyncio
import uuid

import pytest
import pytest_asyncio
import uvicorn
from sqlalchemy import delete, select
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core.crypto import encrypt_secret
from app.models.browser_node import BrowserNode
from app.models.browser_session import BrowserSession
from app.models.enums import BrowserNodeStatus, NodeEnrollmentStatus, SessionStatus
from app.services.sessions import isolate_session, restore_session, terminate_session
from tests.conftest import make_user


class _StubAgent:
    """Records every request path + the X-Openrbi-Agent-Token header it
    received, then returns a minimal valid response for whichever
    endpoint was hit.
    """

    def __init__(self):
        self.requests: list[tuple[str, str, str | None]] = []  # (method, path, token)

    async def handle(self, request):
        self.requests.append(
            (request.method, request.url.path, request.headers.get("x-openrbi-agent-token"))
        )
        return JSONResponse({"host": "127.0.0.1", "port": 5900})


@pytest_asyncio.fixture
async def stub_agent():
    stub = _StubAgent()
    app = Starlette(
        routes=[
            Route("/v1/sandboxes/{session_id}/isolate", stub.handle, methods=["POST"]),
            Route("/v1/sandboxes/{session_id}/restore", stub.handle, methods=["POST"]),
            Route("/v1/sandboxes/{session_id}/terminate", stub.handle, methods=["POST"]),
        ]
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    stub.base_url = f"http://127.0.0.1:{port}"
    yield stub
    server.should_exit = True
    await server_task


async def _make_node(db, *, hostname: str, endpoint_url: str | None, token: str | None) -> BrowserNode:
    node = BrowserNode(
        hostname=hostname,
        status=BrowserNodeStatus.ONLINE,
        enrollment_status=NodeEnrollmentStatus.APPROVED if endpoint_url else NodeEnrollmentStatus.PENDING,
        endpoint_url=endpoint_url,
        agent_token_encrypted=encrypt_secret(token) if token else None,
        capacity=10,
    )
    db.add(node)
    await db.flush()
    return node


async def _delete_test_node(db, node_id: uuid.UUID) -> None:
    from app.models.browser_node import BrowserNode as _Node
    from app.models.incident import Incident
    from app.models.security_event import SecurityEvent

    # FK children before parents — same ordering scripts/e2e-seed.py's
    # cleanup uses: SecurityEvent/Incident reference BrowserSession, which
    # references BrowserNode.
    session_ids = (
        (await db.execute(select(BrowserSession.id).where(BrowserSession.node_id == node_id)))
        .scalars()
        .all()
    )
    if session_ids:
        await db.execute(delete(SecurityEvent).where(SecurityEvent.session_id.in_(session_ids)))
        await db.execute(delete(Incident).where(Incident.session_id.in_(session_ids)))
        await db.execute(delete(BrowserSession).where(BrowserSession.node_id == node_id))
    await db.execute(delete(_Node).where(_Node.id == node_id))
    await db.commit()


@pytest.mark.asyncio
async def test_session_lifecycle_calls_route_to_the_sessions_own_node(db, stub_agent):
    user, _ = await make_user(db, role_name="USER")
    node = await _make_node(
        db, hostname=f"pytest-routing-{uuid.uuid4().hex[:8]}", endpoint_url=stub_agent.base_url, token="stub-node-token"
    )

    session = BrowserSession(user_id=user.id, node_id=node.id, status=SessionStatus.ACTIVE)
    db.add(session)
    await db.flush()
    await db.commit()

    try:
        await isolate_session(db, session, actor_id=user.id)
        assert session.status == SessionStatus.ISOLATED

        await restore_session(db, session, actor_id=user.id)
        assert session.status == SessionStatus.ACTIVE

        await terminate_session(db, session, actor_id=user.id)
        assert session.status == SessionStatus.TERMINATED

        paths = [path for _, path, _ in stub_agent.requests]
        assert paths == [
            f"/v1/sandboxes/{session.id}/isolate",
            f"/v1/sandboxes/{session.id}/restore",
            f"/v1/sandboxes/{session.id}/terminate",
        ]
        # Every call authenticated with this node's own token, decrypted
        # from agent_token_encrypted — never the shared default settings
        # token, and never another node's.
        assert all(token == "stub-node-token" for _, _, token in stub_agent.requests)
    finally:
        await _delete_test_node(db, node.id)


@pytest.mark.asyncio
async def test_a_node_with_no_endpoint_falls_back_to_legacy_settings_unchanged(db):
    """The pre-B2.1 case: a node that exists (e.g. the real single-node
    dev stack's own row) but was never enrolled through the new flow has
    no endpoint_url/agent_token_encrypted. connection_for_node() must fall
    back to the legacy shared settings, not raise or produce a broken
    connection — this is what keeps every existing single-node
    integration test passing unchanged.
    """
    from app.config import get_settings
    from app.services.nodes import connection_for_node

    node = BrowserNode(
        hostname=f"pytest-legacy-{uuid.uuid4().hex[:8]}", status=BrowserNodeStatus.ONLINE, capacity=10
    )
    db.add(node)
    await db.flush()

    try:
        connection = connection_for_node(node)
        settings = get_settings()
        assert connection.base_url == settings.session_agent_base_url
        assert connection.token == settings.session_agent_api_token

        # None (no resolvable node at all) falls back identically.
        none_connection = connection_for_node(None)
        assert none_connection.base_url == settings.session_agent_base_url
    finally:
        await _delete_test_node(db, node.id)
