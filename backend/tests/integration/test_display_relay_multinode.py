"""Roadmap B2.4 (docs/roadmap-b2-multinode.md, docs/adr/0024) — the display
WebSocket now relays through the *session's own node's* Session Agent
instead of dialing a sandbox's VNC port directly. This proves the
backend's display_ws() actually builds the right per-node relay URL and
authenticates with that node's own token — not just the default node's —
using the same lightweight real-second-node technique every other B2
phase's tests use (test_node_routing.py, test_scheduling.py):
a real in-process WebSocket server standing in for a second node's own
`/v1/sandboxes/{id}/display/ws` relay endpoint.

The stub implements only the relay contract (accept, authenticate,
byte-echo) rather than a further nested TCP hop to a fake VNC port — the
real Session Agent's own relay-to-TCP behavior is exercised end to end
by the existing single-node display suite
(test_display_websocket_origin.py) against the real Session Agent/Docker;
this test is specifically about routing to the right node with the right
token, which that suite can't cover since it only ever has one node.
"""

import asyncio
import uuid

import pytest
import pytest_asyncio
import uvicorn
import websockets
from sqlalchemy import delete, select
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect

from app.core.crypto import encrypt_secret
from app.models.browser_node import BrowserNode
from app.models.browser_session import BrowserSession
from app.models.enums import BrowserNodeStatus, NodeEnrollmentStatus, SessionStatus
from app.models.security_event import SecurityEvent
from tests.conftest import login, make_user

_STUB_TOKEN = "stub-node-relay-token"


class _StubRelay:
    def __init__(self):
        self.received_token: str | None = None

    async def relay(self, websocket):
        self.received_token = websocket.headers.get("x-openrbi-agent-token")
        if self.received_token != _STUB_TOKEN:
            await websocket.close(code=4401)
            return
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_bytes()
                await websocket.send_bytes(data)  # pure echo, stands in for the sandbox's VNC port
        except (WebSocketDisconnect, RuntimeError):
            pass


async def _health(request):
    return Response("ok")


@pytest_asyncio.fixture
async def stub_relay_node():
    stub = _StubRelay()
    app = Starlette(
        routes=[
            Route("/health", _health),
            WebSocketRoute("/v1/sandboxes/{session_id}/display/ws", stub.relay),
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


async def _delete_node_and_its_sessions(db, node_id: uuid.UUID) -> None:
    # display_ws()'s own cleanup records a SESSION_DISCONNECTED event for
    # a real client disconnect (app/api/display.py) — security_events
    # must go first (FK), same ordering every other B2-phase test's
    # cleanup uses.
    session_ids = (
        (await db.execute(select(BrowserSession.id).where(BrowserSession.node_id == node_id))).scalars().all()
    )
    if session_ids:
        await db.execute(delete(SecurityEvent).where(SecurityEvent.session_id.in_(session_ids)))
    await db.execute(delete(BrowserSession).where(BrowserSession.node_id == node_id))
    await db.execute(delete(BrowserNode).where(BrowserNode.id == node_id))
    await db.commit()


@pytest.mark.asyncio
async def test_display_ws_relays_through_the_sessions_own_node_with_its_own_token(client, db, stub_relay_node):
    node = BrowserNode(
        hostname=f"pytest-display-{uuid.uuid4().hex[:8]}",
        status=BrowserNodeStatus.ONLINE,
        enrollment_status=NodeEnrollmentStatus.APPROVED,
        endpoint_url=stub_relay_node.base_url,
        agent_token_encrypted=encrypt_secret(_STUB_TOKEN),
        capacity=10,
    )
    db.add(node)
    await db.flush()

    user, password = await make_user(db, role_name="USER")
    session = BrowserSession(user_id=user.id, node_id=node.id, status=SessionStatus.ACTIVE)
    db.add(session)
    await db.commit()
    await db.refresh(session)

    cookie = await login(client, user.username, password)

    try:
        async with websockets.connect(
            f"ws://localhost:8000/display/{session.id}/ws",
            additional_headers={
                "Origin": "http://localhost:8000",
                "Cookie": f"openrbi_session={cookie}",
            },
        ) as ws:
            assert ws.state.name == "OPEN"
            await ws.send(b"\x00hello-from-the-real-client")
            echoed = await asyncio.wait_for(ws.recv(), timeout=5)
            assert echoed == b"\x00hello-from-the-real-client"

        # Proves this reached the stub node's own relay - not the default
        # node's, which would 404/refuse this session id entirely - and
        # authenticated with that node's own decrypted token.
        assert stub_relay_node.received_token == _STUB_TOKEN
    finally:
        # display_ws()'s own cleanup (recording SESSION_DISCONNECTED) runs
        # as a server-side finally block triggered by the client closing
        # above - genuinely concurrent with this test coroutine, not
        # something the `async with` block waits on. A short grace period
        # avoids a cleanup-vs-cleanup race deleting the session out from
        # under that still-in-flight commit.
        await asyncio.sleep(0.3)
        await _delete_node_and_its_sessions(db, node.id)
