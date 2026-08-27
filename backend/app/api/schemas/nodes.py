import uuid
from datetime import datetime

from pydantic import BaseModel

from app.services.worker_health import compute_worker_health, worker_uptime_seconds


class BrowserNodeResponse(BaseModel):
    id: uuid.UUID
    hostname: str
    status: str
    # Roadmap B2.1 — never derived from `health` below: a PENDING/REVOKED
    # node's `enrollment_status` is what an admin needs to act on, and
    # should never be inferred from OFFLINE/DEGRADED-style health noise.
    enrollment_status: str
    endpoint_url: str | None
    # Roadmap B1.10.1 — the centrally-computed label (HEALTHY/DEGRADED/
    # DRAINING/MAINTENANCE/OFFLINE), distinct from `status`: `status` is the
    # raw scheduling flag (ONLINE/DRAINING/OFFLINE/DEGRADED/MAINTENANCE)
    # select_node() acts on; `health` is what an admin should read.
    health: str
    capacity: int
    # Roadmap B3.3 — why `capacity` is what it is right now. "ram"/"cpu"
    # when real headroom is the constraint, "ceiling" when the operator's
    # own OPENRBI_AGENT_CAPACITY is (never a real-headroom concern), None
    # for a node that's never reported yet.
    capacity_bound: str | None
    ram_capacity: int | None
    cpu_capacity: int | None
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
            enrollment_status=node.enrollment_status.value,
            endpoint_url=node.endpoint_url,
            health=compute_worker_health(node).value,
            capacity=node.capacity,
            capacity_bound=node.capacity_bound,
            ram_capacity=node.ram_capacity,
            cpu_capacity=node.cpu_capacity,
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


class WorkerOverviewStats(BaseModel):
    total: int
    healthy: int
    needs_attention: int
    active_sessions: int
    total_capacity: int
    average_cpu_percent: float | None
    average_ram_percent: float | None
    latest_heartbeat: datetime | None


class WorkerOverviewResponse(BaseModel):
    items: list[BrowserNodeResponse]
    total: int
    offset: int
    limit: int
    stats: WorkerOverviewStats


class NodeEnrollmentTokenResponse(BaseModel):
    """Returned exactly once, at generation time — same "shown once" rule
    as MFA recovery codes; the token itself is never persisted in
    Postgres or retrievable again (see app/core/node_enrollment_tokens.py).
    """

    enrollment_token: str
    expires_in_seconds: int


class NodeEnrollRequest(BaseModel):
    enrollment_token: str
    hostname: str
    api_token: str


class NodeApproveRequest(BaseModel):
    endpoint_url: str
