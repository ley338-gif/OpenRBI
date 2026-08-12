from dataclasses import dataclass

import httpx

from app.config import get_settings


@dataclass
class DisplayInfo:
    host: str
    port: int


@dataclass
class NodeStatus:
    hostname: str
    status: str
    capacity: int
    active_sessions: int
    runtime: str
    version: str


class SessionAgentError(RuntimeError):
    pass


def _client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=settings.session_agent_base_url,
        headers={"X-Openrbi-Agent-Token": settings.session_agent_api_token},
        timeout=15.0,
    )


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async with _client() as client:
        try:
            response = await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SessionAgentError(f"session agent unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise SessionAgentError(f"session agent returned {response.status_code}: {response.text}")
    return response


async def get_node_status() -> NodeStatus:
    response = await _request("GET", "/v1/nodes/self")
    body = response.json()
    return NodeStatus(
        hostname=body["hostname"],
        status=body["status"],
        capacity=body["capacity"],
        active_sessions=body["active_sessions"],
        runtime=body["runtime"],
        version=body["version"],
    )


async def create_sandbox(
    session_id: str, *, cpu_limit: float, ram_limit_mb: int, pid_limit: int, disk_limit_mb: int
) -> None:
    await _request(
        "POST",
        f"/v1/sandboxes/{session_id}",
        json={
            "session_id": session_id,
            "cpu_limit": cpu_limit,
            "ram_limit_mb": ram_limit_mb,
            "pid_limit": pid_limit,
            "disk_limit_mb": disk_limit_mb,
        },
    )


async def start_sandbox(session_id: str) -> None:
    await _request("POST", f"/v1/sandboxes/{session_id}/start")


async def isolate_sandbox(session_id: str) -> None:
    await _request("POST", f"/v1/sandboxes/{session_id}/isolate")


async def restore_sandbox(session_id: str) -> None:
    await _request("POST", f"/v1/sandboxes/{session_id}/restore")


async def terminate_sandbox(session_id: str) -> None:
    """Idempotent on the session-agent side (docs/session-lifecycle.md) —
    safe to call even if the sandbox was never successfully created.
    """
    await _request("POST", f"/v1/sandboxes/{session_id}/terminate")


async def get_display_info(session_id: str) -> DisplayInfo:
    """The only way the backend learns where a sandbox's VNC port is —
    it never talks to Docker directly (docs/adr/0005). Fails closed: any
    non-2xx or transport error becomes SessionAgentError, never a guess.
    """
    response = await _request("GET", f"/v1/sandboxes/{session_id}/display")
    body = response.json()
    return DisplayInfo(host=body["host"], port=body["port"])
