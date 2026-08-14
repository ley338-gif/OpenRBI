import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.rfb_clipboard_filter import RfbProtocolError, build_filters
from app.core.session_agent_client import SessionAgentError, get_display_info
from app.db.session import get_db
from app.models.browser_session import BrowserSession
from app.models.enums import SecurityEventType, SessionStatus
from app.models.user import User
from app.services.security_events import record_security_event

router = APIRouter(prefix="/display", tags=["display"])

_CHUNK_SIZE = 65536

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
    session = await db.get(BrowserSession, session_id)
    if session is None or session.user_id != current_user.id:
        await websocket.close(code=_CLOSE_NOT_FOUND)
        return
    if session.status not in (SessionStatus.ACTIVE, SessionStatus.DISCONNECTED):
        await websocket.close(code=_CLOSE_NOT_FOUND)
        return

    try:
        info = await get_display_info(str(session_id))
    except SessionAgentError:
        await websocket.close(code=_CLOSE_SANDBOX_UNREACHABLE)
        return

    # No subprotocol is requested by noVNC's client in this mode (it just
    # relays raw binary WS frames) — accepting with one the client never
    # offered is an invalid handshake response and makes browsers abort the
    # connection immediately despite the HTTP-level 101 succeeding.
    await websocket.accept()

    try:
        reader, writer = await asyncio.open_connection(info.host, info.port)
    except OSError:
        await websocket.close(code=_CLOSE_SANDBOX_UNREACHABLE)
        return

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

    async def pump_ws_to_tcp() -> None:
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
                    writer.write(forward)
                    await writer.drain()
        except (WebSocketDisconnect, OSError):
            pass

    async def pump_tcp_to_ws() -> None:
        try:
            while True:
                data = await reader.read(_CHUNK_SIZE)
                if not data:
                    break
                try:
                    forward = server_filter.feed(data)
                except RfbProtocolError:
                    break
                if forward:
                    await websocket.send_bytes(forward)
        except (WebSocketDisconnect, OSError, RuntimeError):
            pass

    tasks = [asyncio.create_task(pump_ws_to_tcp()), asyncio.create_task(pump_tcp_to_ws())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        _active_connections.pop(session_id, None)
        for task in tasks:
            task.cancel()
        writer.close()
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
