import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.core.deps import get_current_user
from app.core.session_agent_client import SessionAgentError, get_display_info
from app.models.user import User

router = APIRouter(prefix="/display", tags=["display"])

_CHUNK_SIZE = 65536

# Policy close codes (RFC 6455 §7.4.1 private-use range) so the frontend can
# distinguish "you're not allowed" from "the sandbox isn't reachable" rather
# than just seeing a dropped connection.
_CLOSE_SANDBOX_UNREACHABLE = 4502


@router.websocket("/{session_id}/ws")
async def display_ws(websocket: WebSocket, session_id: str, current_user: User = Depends(get_current_user)) -> None:
    """Relays raw RFB/VNC bytes between the end user's noVNC client and the
    sandbox's VNC port. get_current_user (a websocket-compatible FastAPI
    dependency) fails the handshake closed before accept() for any
    unauthenticated/inactive caller — see docs/security-model.md.

    Ownership of session_id (this user actually owns it, or is an admin/
    reviewer) is not yet enforced here — BrowserSession records don't exist
    until Phase 10/11 wires the real session lifecycle. Tracked there.
    """
    try:
        info = await get_display_info(session_id)
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

    async def pump_ws_to_tcp() -> None:
        try:
            while True:
                data = await websocket.receive_bytes()
                writer.write(data)
                await writer.drain()
        except (WebSocketDisconnect, OSError):
            pass

    async def pump_tcp_to_ws() -> None:
        try:
            while True:
                data = await reader.read(_CHUNK_SIZE)
                if not data:
                    break
                await websocket.send_bytes(data)
        except (WebSocketDisconnect, OSError, RuntimeError):
            pass

    tasks = [asyncio.create_task(pump_ws_to_tcp()), asyncio.create_task(pump_tcp_to_ws())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        writer.close()
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass  # already closed by the client
