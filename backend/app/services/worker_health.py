"""Roadmap Phase B / B1.10.1 — the single, centrally-defined mapping from a
BrowserNode row's raw state to the admin-facing health label. Every place
that needs to answer "is this worker healthy" (the Workers list, a worker
detail page, the dashboard's aggregate counts, System Health) calls
`compute_worker_health()` — never re-derives its own notion of "healthy"
from `BrowserNode.status`/`last_heartbeat`/telemetry independently.

Definitions (matches the task's own spec):
  MAINTENANCE — admin has explicitly taken the node out of service.
  OFFLINE     — heartbeat missing or older than node_heartbeat_stale_seconds.
                Checked before everything else: a status field from a stale
                row is not trustworthy either.
  DRAINING    — admin has stopped new scheduling; existing sessions continue.
  DEGRADED    — node is reachable and not draining/in-maintenance, but
                either self-reports DEGRADED or its own CPU/RAM usage is at
                or above the configured threshold.
  HEALTHY     — none of the above.
"""

import enum
from datetime import UTC, datetime

from app.config import get_settings
from app.models.browser_node import BrowserNode
from app.models.enums import BrowserNodeStatus


class WorkerHealth(str, enum.Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DRAINING = "DRAINING"
    MAINTENANCE = "MAINTENANCE"
    OFFLINE = "OFFLINE"


def is_heartbeat_stale(node: BrowserNode, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    if node.last_heartbeat is None:
        return True
    settings = get_settings()
    return (now - node.last_heartbeat).total_seconds() > settings.node_heartbeat_stale_seconds


def compute_worker_health(node: BrowserNode, *, now: datetime | None = None) -> WorkerHealth:
    if node.status == BrowserNodeStatus.MAINTENANCE:
        return WorkerHealth.MAINTENANCE

    if is_heartbeat_stale(node, now=now):
        return WorkerHealth.OFFLINE

    if node.status == BrowserNodeStatus.DRAINING:
        return WorkerHealth.DRAINING

    if node.status == BrowserNodeStatus.DEGRADED:
        return WorkerHealth.DEGRADED

    settings = get_settings()
    if node.cpu_percent is not None and node.cpu_percent >= settings.node_cpu_degraded_percent:
        return WorkerHealth.DEGRADED
    if (
        node.ram_total_mb is not None
        and node.ram_total_mb > 0
        and node.ram_used_mb is not None
        and (node.ram_used_mb / node.ram_total_mb) * 100 >= settings.node_ram_degraded_percent
    ):
        return WorkerHealth.DEGRADED

    return WorkerHealth.HEALTHY


def worker_uptime_seconds(node: BrowserNode, *, now: datetime | None = None) -> int | None:
    if node.node_started_at is None:
        return None
    now = now or datetime.now(UTC)
    return max(0, int((now - node.node_started_at).total_seconds()))
