from datetime import UTC, datetime

from fastapi import Depends, FastAPI

from app.api.sandboxes import router as sandboxes_router
from app.auth import require_control_plane_token
from app.config import get_settings
from app.providers.factory import get_provider

app = FastAPI(
    title="OpenRBI Session Agent",
    version="0.1.0",
    description=(
        "Internal-only privileged service for browser sandbox lifecycle. "
        "Not exposed publicly; see docs/adr/0004 and 0005."
    ),
)

app.include_router(sandboxes_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/nodes/self", dependencies=[Depends(require_control_plane_token)])
async def node_status() -> dict[str, str | int]:
    """Real BrowserNode self-report (capacity/active_sessions/runtime/
    version) — the control plane's Phase 23 heartbeat loop polls this to
    populate the BrowserNode row. Single-node MVP 1 still models this as a
    first-class, polled status rather than assumed-always-online (see
    docs/architecture.md#multi-node-readiness).
    """
    settings = get_settings()
    provider = get_provider()
    active_sessions = await provider.count_active_sessions()
    version = await provider.runtime_version()
    return {
        "status": "ONLINE",
        "capacity": _capacity_from_settings(settings),
        "active_sessions": active_sessions,
        "runtime": "docker",
        "version": version,
        "heartbeat_at": datetime.now(UTC).isoformat(),
    }


def _capacity_from_settings(settings) -> int:
    # Placeholder capacity model: MVP 1 has no host-resource-aware scheduler
    # yet (Phase 23 note in docs/architecture.md); a fixed ceiling keeps
    # get_status() honest about "no free slots" without pretending to know
    # real host headroom.
    return 10
