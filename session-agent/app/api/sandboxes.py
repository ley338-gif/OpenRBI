import asyncio
import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.auth import require_control_plane_token
from app.config import get_settings
from app.providers.base import SandboxConfig, SandboxRuntimeStatus
from app.providers.factory import get_provider
from app.schemas import (
    CreateSandboxRequest,
    DisplayInfoResponse,
    DownloadedFileResponse,
    MetricsResponse,
    StatusResponse,
)

logger = logging.getLogger("openrbi.sandboxes")

_CHUNK_SIZE = 65536
# Roadmap B2.4 close code for "couldn't reach the sandbox's display" —
# distinct from a plain protocol-level close so the control plane's own
# relay client (app/api/display.py) can tell "this node is fine but the
# sandbox inside it isn't" apart from any other WebSocket failure.
_CLOSE_DISPLAY_UNREACHABLE = 4502

router = APIRouter(
    prefix="/v1/sandboxes", tags=["sandboxes"], dependencies=[Depends(require_control_plane_token)]
)


@router.get("", response_model=list[str])
async def list_active_sandboxes(include_stopped: bool = False) -> list[str]:
    """Session IDs of every currently running openrbi.managed container —
    the minimal addition the control plane's orphan reconciliation job
    (app/core/orphan_reconciler.py) needs to compare live containers
    against BrowserSession rows. Deliberately separate from
    count_active_sessions() (used by /v1/nodes/self), not a change to that
    method's existing int return contract.
    """
    if include_stopped:
        return await get_provider().list_managed_session_ids()
    return await get_provider().list_active_session_ids()


@router.post("/{session_id}", status_code=status.HTTP_201_CREATED)
async def create_sandbox(session_id: str, payload: CreateSandboxRequest) -> dict[str, str]:
    settings = get_settings()
    config = SandboxConfig(
        image=payload.image or settings.sandbox_image,
        cpu_limit=payload.cpu_limit or settings.default_cpu_limit,
        ram_limit_mb=payload.ram_limit_mb or settings.default_ram_limit_mb,
        pid_limit=payload.pid_limit or settings.default_pid_limit,
        disk_limit_mb=payload.disk_limit_mb or settings.default_disk_limit_mb,
        network_name=settings.sandbox_network_name,
        screen_width=payload.screen_width or settings.default_screen_width,
        screen_height=payload.screen_height or settings.default_screen_height,
        command=settings.sandbox_command,
    )
    try:
        await get_provider().create_session(session_id, config)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — always a JSON error, never a raw 500
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"status": "created"}


@router.post("/{session_id}/start")
async def start_sandbox(session_id: str) -> dict[str, str]:
    try:
        await get_provider().start_session(session_id)
    except Exception as exc:  # noqa: BLE001 — surfaced as a 502, never silently swallowed
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"status": "started"}


@router.post("/{session_id}/isolate")
async def isolate_sandbox(session_id: str) -> dict[str, str]:
    try:
        await get_provider().isolate_session(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"status": "isolated"}


@router.post("/{session_id}/restore")
async def restore_sandbox(session_id: str) -> dict[str, str]:
    try:
        await get_provider().restore_session(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"status": "restored"}


@router.post("/{session_id}/terminate")
async def terminate_sandbox(session_id: str) -> dict[str, str]:
    """Idempotent — see docs/session-lifecycle.md. Never raises just because
    the sandbox was already gone.
    """
    try:
        await get_provider().terminate_session(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"status": "terminated"}


@router.get("/{session_id}/status", response_model=StatusResponse)
async def sandbox_status(session_id: str) -> StatusResponse:
    result = await get_provider().get_status(session_id)
    return StatusResponse(
        status=result.status.value, container_id=result.container_id, started_at=result.started_at, detail=result.detail
    )


@router.get("/{session_id}/display", response_model=DisplayInfoResponse)
async def sandbox_display_info(session_id: str) -> DisplayInfoResponse:
    try:
        info = await get_provider().get_display_info(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return DisplayInfoResponse(host=info.host, port=info.port)


@router.get("/{session_id}/display/ready")
async def sandbox_display_ready(session_id: str) -> dict[str, str]:
    """Roadmap B2.4 (docs/adr/0024) — the local liveness probe
    app/services/sessions.py's _wait_for_display_ready() used to perform
    itself, from the backend, by dialing the sandbox's VNC port directly.
    That only worked because the backend used to be multi-homed onto the
    same browser-plane bridge every sandbox lives on; once a node can be
    on a different host entirely, only this process (which genuinely is
    on that bridge) can still make that connection. Returns 200 once a
    real TCP handshake to the sandbox's VNC port succeeds, 502 otherwise
    — the backend polls this with its own retry/backoff loop, unchanged
    from before.
    """
    try:
        info = await get_provider().get_display_info(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(info.host, info.port), timeout=2.0)
    except (OSError, TimeoutError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"display not ready: {exc}") from exc
    writer.close()
    return {"status": "ready"}


@router.websocket("/{session_id}/display/ws")
async def sandbox_display_relay(
    websocket: WebSocket, session_id: str, _: None = Depends(require_control_plane_token)
) -> None:
    """Roadmap B2.4 (docs/adr/0024) — the control plane no longer dials a
    sandbox's VNC port directly (impossible once the sandbox lives on a
    different host's private browser-plane bridge than the backend); it
    dials this relay instead, authenticated exactly like every other
    route on this router. This process resolves the sandbox's real
    host:port locally (same provider call the REST /display endpoint
    above uses) and pumps raw bytes between the two — a dumb byte pipe.
    Clipboard-policy filtering and every other access-control decision
    stay entirely on the control-plane side (app/api/display.py); this
    relay never inspects or modifies the stream, only carries it.
    """
    try:
        info = await get_provider().get_display_info(session_id)
    except Exception:
        logger.exception("display relay: could not resolve display info for session %s", session_id)
        await websocket.close(code=_CLOSE_DISPLAY_UNREACHABLE)
        return

    await websocket.accept()

    try:
        reader, writer = await asyncio.open_connection(info.host, info.port)
    except OSError:
        await websocket.close(code=_CLOSE_DISPLAY_UNREACHABLE)
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
            pass


@router.get("/{session_id}/downloads", response_model=list[DownloadedFileResponse])
async def list_downloads(session_id: str) -> list[DownloadedFileResponse]:
    try:
        files = await get_provider().list_downloads(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return [DownloadedFileResponse(filename=f.filename, size_bytes=f.size_bytes) for f in files]


@router.get("/{session_id}/downloads/{filename}")
async def fetch_download(session_id: str, filename: str) -> Response:
    try:
        data, origin_url = await get_provider().fetch_download(session_id, filename)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    headers = {"X-Openrbi-Origin-Url": origin_url} if origin_url else {}
    return Response(content=data, media_type="application/octet-stream", headers=headers)


@router.delete("/{session_id}/downloads/{filename}")
async def delete_download(session_id: str, filename: str) -> dict[str, str]:
    try:
        await get_provider().delete_download(session_id, filename)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"status": "deleted"}


@router.put("/{session_id}/uploads/{filename}")
async def write_upload(session_id: str, filename: str, request: Request) -> dict[str, str]:
    data = await request.body()
    try:
        await get_provider().write_upload(session_id, filename, data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"status": "written"}


@router.get("/{session_id}/metrics", response_model=MetricsResponse)
async def sandbox_metrics(session_id: str) -> MetricsResponse:
    status_result = await get_provider().get_status(session_id)
    if status_result.status == SandboxRuntimeStatus.NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sandbox not found")
    try:
        metrics = await get_provider().get_metrics(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return MetricsResponse(**metrics.__dict__)
