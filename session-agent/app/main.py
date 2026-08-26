import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import psutil
from fastapi import Depends, FastAPI

from app import enrollment
from app.api.sandboxes import router as sandboxes_router
from app.auth import require_control_plane_token
from app.build_info import BUILD_INFO
from app.config import get_settings
from app.providers.factory import get_provider


@asynccontextmanager
async def _lifespan(app: FastAPI):
    enrollment.start()
    yield
    enrollment.stop()


app = FastAPI(
    title="OpenRBI Session Agent",
    version=BUILD_INFO.version,
    description=(
        "Internal-only privileged service for browser sandbox lifecycle. "
        "Not exposed publicly; see docs/adr/0004 and 0005."
    ),
    lifespan=_lifespan,
)

app.include_router(sandboxes_router)

# Roadmap B1.10.1 — a throwaway first call at import time: psutil.cpu_percent()
# measures the delta since its *previous* call, so an uncalled first
# invocation from a real request would report a meaningless 0.0 (or the
# usage since machine boot). This warms it up once so the first real
# /v1/nodes/self response is already a real short-window sample.
psutil.cpu_percent(interval=None)
_PROCESS_STARTED_AT = datetime.fromtimestamp(psutil.Process(os.getpid()).create_time(), tz=UTC)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", **BUILD_INFO.as_dict()}


@app.get("/v1/nodes/self", dependencies=[Depends(require_control_plane_token)])
async def node_status() -> dict[str, str | int | float | bool]:
    """Real BrowserNode self-report (capacity/active_sessions/runtime/
    version/CPU/RAM) — the control plane's poller (app/core/node_poller.py)
    and select_node() both call this to populate the BrowserNode row.
    Single-node MVP 1 still models this as a first-class, polled status
    rather than assumed-always-online (see docs/architecture.md#multi-node-readiness).

    CPU/RAM are host-wide (psutil.cpu_percent/virtual_memory), not scoped to
    this container's own cgroup — deliberately: the browser sandboxes this
    agent manages are sibling containers on the same host, so host-wide
    load is what "how loaded is this worker" actually means for an
    operator, not just this one process's own footprint.
    """
    settings = get_settings()
    provider = get_provider()
    active_sessions = await provider.count_active_sessions()
    version = await provider.runtime_version()
    image_available = await provider.sandbox_image_available(settings.sandbox_image)
    memory = psutil.virtual_memory()
    return {
        "hostname": settings.node_name,
        "status": "ONLINE",
        "capacity": _capacity_from_settings(settings),
        "active_sessions": active_sessions,
        "runtime": "docker",
        "version": version,
        "sandbox_image_available": image_available,
        "heartbeat_at": datetime.now(UTC).isoformat(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_total_mb": int(memory.total / (1024 * 1024)),
        "ram_used_mb": int((memory.total - memory.available) / (1024 * 1024)),
        "node_started_at": _PROCESS_STARTED_AT.isoformat(),
    }


def _capacity_from_settings(settings) -> int:
    # Placeholder capacity model: MVP 1 has no host-resource-aware scheduler
    # yet (Phase 23 note in docs/architecture.md); a fixed ceiling keeps
    # get_status() honest about "no free slots" without pretending to know
    # real host headroom.
    return 10
