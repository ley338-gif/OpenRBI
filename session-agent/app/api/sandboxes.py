from fastapi import APIRouter, Depends, HTTPException, Response, status

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

router = APIRouter(
    prefix="/v1/sandboxes", tags=["sandboxes"], dependencies=[Depends(require_control_plane_token)]
)


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
