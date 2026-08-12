from dataclasses import dataclass

import httpx

from app.config import get_settings


@dataclass
class DisplayInfo:
    host: str
    port: int


class SessionAgentError(RuntimeError):
    pass


def _client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=settings.session_agent_base_url,
        headers={"X-Openrbi-Agent-Token": settings.session_agent_api_token},
        timeout=10.0,
    )


async def get_display_info(session_id: str) -> DisplayInfo:
    """The only way the backend learns where a sandbox's VNC port is —
    it never talks to Docker directly (docs/adr/0005). Fails closed: any
    non-2xx or transport error becomes SessionAgentError, never a guess.
    """
    async with _client() as client:
        try:
            response = await client.get(f"/v1/sandboxes/{session_id}/display")
        except httpx.HTTPError as exc:
            raise SessionAgentError(f"session agent unreachable: {exc}") from exc
    if response.status_code != 200:
        raise SessionAgentError(f"session agent returned {response.status_code}: {response.text}")
    body = response.json()
    return DisplayInfo(host=body["host"], port=body["port"])
