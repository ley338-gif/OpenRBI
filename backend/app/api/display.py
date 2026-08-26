import asyncio
import uuid
from datetime import UTC, datetime

import websockets
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.core.deps import get_current_user
from app.core.rfb_clipboard_filter import RfbProtocolError, build_filters
from app.db.session import get_db
from app.models.browser_session import BrowserSession
from app.models.enums import SecurityEventType, SessionStatus
from app.models.user import User
from app.services.nodes import connection_for_node, get_node
from app.services.security_events import record_security_event

router = APIRouter(prefix="/display", tags=["display"])

# Policy close codes (RFC 6455 §7.4.1 private-use range) so the frontend can
# distinguish "you're not allowed" from "the sandbox isn't reachable" rather
# than just seeing a dropped connection.
_CLOSE_NOT_FOUND = 4404
_CLOSE_SANDBOX_UNREACHABLE = 4502
_CLOSE_ADMIN_DISCONNECTED = 4001

# In-process registry of live display connections, keyed by session id, so
# an admin-triggered disconnect (app/api/admin_sessions.py, Phase 11) can
# actually close a session's active websocket rather than only flipping a
# database flag the client won't notice until its next action. Single
# backend process for MVP 1 (docs/architecture.md's multi-node note) — a
# real multi-instance deployment would need this shared (e.g. via Redis
# pub/sub) instead of in-process.
_active_connections: dict[uuid.UUID, WebSocket] = {}


async def force_disconnect(session_id: uuid.UUID) -> bool:
    """Returns True if a live connection was found and closed."""
    websocket = _active_connections.get(session_id)
    if websocket is None:
        return False
    await websocket.close(code=_CLOSE_ADMIN_DISCONNECTED)
    return True


def discard_stale_connection(session_id: uuid.UUID) -> None:
    """Drops a registry entry without trying to gracefully close it first —
    for app/core/orphan_reconciler.py's lost-session direction, where the
    entry (if any) belongs to a container that's already gone, so there is
    no live peer left to send a close frame to. force_disconnect() assumes
    a reachable peer and isn't a fit here.
    """
    _active_connections.pop(session_id, None)


@router.websocket("/{session_id}/ws")
async def display_ws(
    websocket: WebSocket,
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Relays raw RFB/VNC bytes between the end user's noVNC client and the
    sandbox's VNC port. get_current_user fails the handshake closed before
    accept() for any unauthenticated/inactive caller.

    Ownership is enforced the same way as the REST session endpoints
    (app/api/sessions.py): a session that exists but belongs to someone
    else is indistinguishable from one that doesn't exist. Admin/reviewer
    access to other users' sessions is Phase 11, a distinct audited path.
    """
    # RBI-POST-003: CSRF defenses elsewhere in the app (app/core/csrf.py)
    # can't reach a WebSocket upgrade request — there's no way for the
    # frontend to attach a custom header to the handshake itself. Origin
    # validation is the equivalent control here: a real browser always
    # sends Origin on a WS handshake (same-origin or not), so a mismatch
    # means this isn't our own frontend making the request. Compares only
    # the host component (not scheme) against the Host header — behind
    # docker-compose.prod.yml's reverse proxy, TLS terminates at nginx and
    # this process only ever sees the plain-HTTP hop to it, so comparing
    # scheme would reject every legitimate request in that deployment.
    origin = websocket.headers.get("origin")
    if origin is not None:
        origin_host = origin.split("://", 1)[-1]
        if origin_host != websocket.headers.get("host"):
            await websocket.close(code=_CLOSE_NOT_FOUND)
            return

    session = await db.get(BrowserSession, session_id)
    if session is None or session.user_id != current_user.id:
        await websocket.close(code=_CLOSE_NOT_FOUND)
        return
    if session.status not in (SessionStatus.ACTIVE, SessionStatus.DISCONNECTED):
        await websocket.close(code=_CLOSE_NOT_FOUND)
        return

    # Roadmap B2.4 (docs/adr/0024) — the backend no longer dials the
    # sandbox's VNC port directly (it can't, once the sandbox is on a
    # different host's private browser-plane bridge); it dials that
    # node's own Session Agent relay instead, over a second WebSocket
    # authenticated with the node's own per-node token. Every check above
    # (ownership, status, Origin) and every filter below is completely
    # unchanged — the relay hop only ever carries bytes this handler has
    # already decided are allowed to cross it.
    connection = connection_for_node(await get_node(db, session.node_id))
    relay_url = connection.base_url.rstrip("/") + f"/v1/sandboxes/{session_id}/display/ws"
    if relay_url.startswith("https://"):
        relay_url = "wss://" + relay_url[len("https://") :]
    elif relay_url.startswith("http://"):
        relay_url = "ws://" + relay_url[len("http://") :]

    try:
        agent_ws = await websockets.connect(
            relay_url,
            additional_headers={"X-Openrbi-Agent-Token": connection.token},
            open_timeout=10,
        )
    except (OSError, WebSocketException):
        await websocket.close(code=_CLOSE_SANDBOX_UNREACHABLE)
        return

    # No subprotocol is requested by noVNC's client in this mode (it just
    # relays raw binary WS frames) — accepting with one the client never
    # offered is an invalid handshake response and makes browsers abort the
    # connection immediately despite the HTTP-level 101 succeeding.
    await websocket.accept()

    session.status = SessionStatus.ACTIVE
    session.last_activity_at = datetime.now(UTC)
    await db.commit()

    _active_connections[session_id] = websocket

    # Real, protocol-level clipboard-policy enforcement (docs/policies.md) —
    # not a UI-only control. See app/core/rfb_clipboard_filter.py for the
    # design and its documented trade-offs/residual risk. For the common
    # unrestricted case (BIDIRECTIONAL_TEXT) both filters are a no-op pure
    # passthrough with no parsing overhead.
    client_filter, server_filter = build_filters(session.clipboard_mode)

    async def pump_ws_to_agent() -> None:
        try:
            while True:
                data = await websocket.receive_bytes()
                try:
                    forward = client_filter.feed(data)
                except RfbProtocolError:
                    # Fail-closed: an unparseable byte sequence could be a
                    # clipboard message this filter failed to recognize —
                    # never guess and keep relaying, tear the connection
                    # down instead.
                    break
                if forward:
                    await agent_ws.send(forward)
        except (WebSocketDisconnect, OSError, ConnectionClosed):
            pass

    async def pump_agent_to_ws() -> None:
        try:
            while True:
                data = await agent_ws.recv()
                if isinstance(data, str):
                    data = data.encode()  # the relay only ever sends bytes; defensive only
                try:
                    forward = server_filter.feed(data)
                except RfbProtocolError:
                    break
                if forward:
                    await websocket.send_bytes(forward)
        except (WebSocketDisconnect, OSError, RuntimeError, ConnectionClosed):
            pass

    tasks = [asyncio.create_task(pump_ws_to_agent()), asyncio.create_task(pump_agent_to_ws())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        _active_connections.pop(session_id, None)
        for task in tasks:
            task.cancel()
        await agent_ws.close()
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass  # already closed by the client

        # The sandbox itself is untouched by a display disconnect — only
        # the remote-display connection drops (docs/session-lifecycle.md).
        # A TERMINATING/TERMINATED/FAILED session must not be bumped back
        # to DISCONNECTED just because its display connection also closed.
        await db.refresh(session)
        needs_commit = False
        if session.status == SessionStatus.ACTIVE:
            session.status = SessionStatus.DISCONNECTED
            await record_security_event(
                db, SecurityEventType.SESSION_DISCONNECTED, user_id=current_user.id, session_id=session.id
            )
            needs_commit = True
        if client_filter.blocked_once or server_filter.blocked_once:
            # Once per connection, not once per blocked message — an
            # actively-clipboard-blocked user could otherwise flood the
            # audit log with one event per copy/paste attempt.
            await record_security_event(
                db, SecurityEventType.CLIPBOARD_ACCESS_BLOCKED, user_id=current_user.id, session_id=session.id
            )
            needs_commit = True
        if needs_commit:
            await db.commit()
