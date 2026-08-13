import uuid
from datetime import datetime

from pydantic import BaseModel

from app.services.worker_health import compute_worker_health, worker_uptime_seconds


class BrowserNodeResponse(BaseModel):
    id: uuid.UUID
    hostname: str
    status: str
    # Roadmap B1.10.1 — the centrally-computed label (HEALTHY/DEGRADED/
    # DRAINING/MAINTENANCE/OFFLINE), distinct from `status`: `status` is the
    # raw scheduling flag (ONLINE/DRAINING/OFFLINE/DEGRADED/MAINTENANCE)
    # select_node() acts on; `health` is what an admin should read.
    health: str
    capacity: int
    active_sessions: int
    runtime: str
    version: str | None
    last_heartbeat: datetime | None
    cpu_percent: float | None
    ram_total_mb: int | None
    ram_used_mb: int | None
    uptime_seconds: int | None

    @classmethod
    def from_model(cls, node) -> "BrowserNodeResponse":
        return cls(
            id=node.id,
            hostname=node.hostname,
            status=node.status.value,
            health=compute_worker_health(node).value,
            capacity=node.capacity,
            active_sessions=node.active_sessions,
            runtime=node.runtime,
            version=node.version,
            last_heartbeat=node.last_heartbeat,
            cpu_percent=node.cpu_percent,
            ram_total_mb=node.ram_total_mb,
            ram_used_mb=node.ram_used_mb,
            uptime_seconds=worker_uptime_seconds(node),
        )


class NodeHistoryPointResponse(BaseModel):
    """Roadmap B1.10.3 — one bucketed point of a single worker's CPU/RAM/
    session history (Worker Detail view graphs)."""

    t: datetime
    cpu_percent: float | None
    ram_percent: float | None
    active_sessions: int
