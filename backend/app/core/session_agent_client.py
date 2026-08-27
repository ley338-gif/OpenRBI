from dataclasses import dataclass
from datetime import datetime

import httpx

from app.config import get_settings


@dataclass
class NodeConnection:
    """Roadmap B2.2 — where to reach a specific node's Session Agent and
    what to authenticate with. Every function below accepts one as an
    optional keyword arg; omitting it (every call site before this phase,
    and the still-single-node-scoped callers below) falls back to the
    legacy settings.session_agent_base_url/api_token, so nothing about the
    single-node case changes. See app/services/nodes.py's
    connection_for_node() for how one gets built from a real BrowserNode.
    """

    base_url: str
    token: str


@dataclass
class DisplayInfo:
    host: str
    port: int


@dataclass
class DownloadedFile:
    filename: str
    size_bytes: int


@dataclass
class NodeStatus:
    hostname: str
    status: str
    capacity: int
    # Roadmap B3.3 — why `capacity` is what it is right now: "ram"/"cpu"
    # when real headroom is the constraint, "ceiling" when the operator's
    # own OPENRBI_AGENT_CAPACITY is (never a real-headroom concern).
    capacity_bound: str
    ram_capacity: int
    cpu_capacity: int
    active_sessions: int
    runtime: str
    version: str
    sandbox_image_available: bool
    cpu_percent: float
    ram_total_mb: int
    ram_used_mb: int
    node_started_at: datetime


class SessionAgentError(RuntimeError):
    pass


def _client(connection: NodeConnection | None = None) -> httpx.AsyncClient:
    if connection is None:
        settings = get_settings()
        connection = NodeConnection(base_url=settings.session_agent_base_url, token=settings.session_agent_api_token)
    return httpx.AsyncClient(
        base_url=connection.base_url,
        headers={"X-Openrbi-Agent-Token": connection.token},
        timeout=15.0,
    )


async def _request(
    method: str, path: str, *, connection: NodeConnection | None = None, **kwargs
) -> httpx.Response:
    async with _client(connection) as client:
        try:
            response = await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SessionAgentError(f"session agent unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise SessionAgentError(f"session agent returned {response.status_code}: {response.text}")
    return response


async def get_node_status(*, connection: NodeConnection | None = None) -> NodeStatus:
    response = await _request("GET", "/v1/nodes/self", connection=connection)
    body = response.json()
    return NodeStatus(
        hostname=body["hostname"],
        status=body["status"],
        capacity=body["capacity"],
        capacity_bound=body["capacity_bound"],
        ram_capacity=body["ram_capacity"],
        cpu_capacity=body["cpu_capacity"],
        active_sessions=body["active_sessions"],
        runtime=body["runtime"],
        version=body["version"],
        sandbox_image_available=body["sandbox_image_available"],
        cpu_percent=body["cpu_percent"],
        ram_total_mb=body["ram_total_mb"],
        ram_used_mb=body["ram_used_mb"],
        node_started_at=datetime.fromisoformat(body["node_started_at"]),
    )


async def check_display_ready(session_id: str, *, connection: NodeConnection | None = None) -> bool:
    """Roadmap B2.4 (docs/adr/0024) — the control plane can't TCP-dial a
    sandbox's VNC port itself any more (it's only reachable from the node
    it's actually on), so it asks that node's own agent to check instead.
    Returns False rather than raising for the specific "not ready yet"
    case (a 502 from the agent's own probe) so app/services/sessions.py's
    retry loop can treat it identically to how it always treated a failed
    direct TCP connect; any other failure (the node itself unreachable)
    still raises SessionAgentError like every other call here.
    """
    async with _client(connection) as client:
        try:
            response = await client.get(f"/v1/sandboxes/{session_id}/display/ready")
        except httpx.HTTPError as exc:
            raise SessionAgentError(f"session agent unreachable: {exc}") from exc
    if response.status_code == 502:
        return False
    if response.status_code >= 400:
        raise SessionAgentError(f"session agent returned {response.status_code}: {response.text}")
    return True


async def list_active_sandboxes(*, connection: NodeConnection | None = None) -> list[str]:
    """Session IDs of every currently running openrbi.managed container on
    the node — used by app/core/orphan_reconciler.py to reconcile against
    BrowserSession rows. Fails closed like every other call here: a
    SessionAgentError propagates rather than being treated as "no
    containers".
    """
    response = await _request("GET", "/v1/sandboxes", connection=connection)
    return response.json()


async def list_managed_sandboxes(*, connection: NodeConnection | None = None) -> list[str]:
    """Session IDs for all managed containers, including stopped ones.

    Reconciliation needs this wider inventory to clean up resources left by
    a hard container kill or an interrupted startup.  Scheduling/capacity
    still uses the running-only inventory above.
    """
    response = await _request(
        "GET", "/v1/sandboxes", params={"include_stopped": "true"}, connection=connection
    )
    return response.json()


async def create_sandbox(
    session_id: str,
    *,
    cpu_limit: float,
    ram_limit_mb: int,
    pid_limit: int,
    disk_limit_mb: int,
    screen_width: int,
    screen_height: int,
    connection: NodeConnection | None = None,
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
            "screen_width": screen_width,
            "screen_height": screen_height,
        },
        connection=connection,
    )


async def start_sandbox(session_id: str, *, connection: NodeConnection | None = None) -> None:
    await _request("POST", f"/v1/sandboxes/{session_id}/start", connection=connection)


async def isolate_sandbox(session_id: str, *, connection: NodeConnection | None = None) -> None:
    await _request("POST", f"/v1/sandboxes/{session_id}/isolate", connection=connection)


async def restore_sandbox(session_id: str, *, connection: NodeConnection | None = None) -> None:
    await _request("POST", f"/v1/sandboxes/{session_id}/restore", connection=connection)


async def terminate_sandbox(session_id: str, *, connection: NodeConnection | None = None) -> None:
    """Idempotent on the session-agent side (docs/session-lifecycle.md) —
    safe to call even if the sandbox was never successfully created.
    """
    await _request("POST", f"/v1/sandboxes/{session_id}/terminate", connection=connection)


async def get_display_info(session_id: str, *, connection: NodeConnection | None = None) -> DisplayInfo:
    """The only way the backend learns where a sandbox's VNC port is —
    it never talks to Docker directly (docs/adr/0005). Fails closed: any
    non-2xx or transport error becomes SessionAgentError, never a guess.
    """
    response = await _request("GET", f"/v1/sandboxes/{session_id}/display", connection=connection)
    body = response.json()
    return DisplayInfo(host=body["host"], port=body["port"])


async def list_downloads(session_id: str, *, connection: NodeConnection | None = None) -> list[DownloadedFile]:
    response = await _request("GET", f"/v1/sandboxes/{session_id}/downloads", connection=connection)
    return [DownloadedFile(filename=f["filename"], size_bytes=f["size_bytes"]) for f in response.json()]


async def fetch_download(
    session_id: str, filename: str, *, connection: NodeConnection | None = None
) -> tuple[bytes, str | None]:
    """Reaches into the sandbox filesystem only via the Session Agent's
    Docker API access (docs/adr/0005) — never a network path from the
    backend into the browser-plane subnet for this purpose.
    """
    response = await _request(
        "GET", f"/v1/sandboxes/{session_id}/downloads/{filename}", connection=connection
    )
    return response.content, response.headers.get("X-Openrbi-Origin-Url")


async def delete_download(session_id: str, filename: str, *, connection: NodeConnection | None = None) -> None:
    await _request("DELETE", f"/v1/sandboxes/{session_id}/downloads/{filename}", connection=connection)


async def write_upload(
    session_id: str, filename: str, data: bytes, *, connection: NodeConnection | None = None
) -> None:
    """The only way bytes get into the sandbox — never a direct mount
    (docs/security-model.md), and never a network path the backend opens
    into the sandbox itself; the Session Agent writes it via its own
    Docker exec access (docs/adr/0005).
    """
    await _request(
        "PUT", f"/v1/sandboxes/{session_id}/uploads/{filename}", content=data, connection=connection
    )
