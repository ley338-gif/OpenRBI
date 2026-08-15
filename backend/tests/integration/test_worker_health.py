"""Roadmap Phase B / B1.10.1 — pure unit coverage for the single, central
Healthy/Degraded/Draining/Maintenance/Offline mapping
(app/services/worker_health.py). Deliberately does not touch the database
or the real Session Agent — compute_worker_health() is a pure function of
a BrowserNode's already-loaded fields, so these run fast and don't need
`db`/`client`.
"""

from datetime import UTC, datetime, timedelta


from app.models.browser_node import BrowserNode
from app.models.enums import BrowserNodeStatus
from app.services.worker_health import WorkerHealth, compute_worker_health, worker_uptime_seconds

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _node(**overrides) -> BrowserNode:
    defaults = dict(
        hostname="test-node",
        status=BrowserNodeStatus.ONLINE,
        capacity=10,
        active_sessions=0,
        last_heartbeat=NOW,
        cpu_percent=10.0,
        ram_total_mb=1000,
        ram_used_mb=100,
        node_started_at=NOW - timedelta(days=1),
    )
    defaults.update(overrides)
    return BrowserNode(**defaults)


def test_healthy_node():
    assert compute_worker_health(_node(), now=NOW) == WorkerHealth.HEALTHY


def test_maintenance_wins_over_everything_else():
    node = _node(status=BrowserNodeStatus.MAINTENANCE, last_heartbeat=None, cpu_percent=99.0)
    assert compute_worker_health(node, now=NOW) == WorkerHealth.MAINTENANCE


def test_stale_heartbeat_is_offline_even_if_status_says_online():
    node = _node(last_heartbeat=NOW - timedelta(minutes=5))
    assert compute_worker_health(node, now=NOW) == WorkerHealth.OFFLINE


def test_never_reported_at_all_is_offline_not_idle():
    node = _node(last_heartbeat=None)
    assert compute_worker_health(node, now=NOW) == WorkerHealth.OFFLINE


def test_offline_check_precedes_draining_status():
    # A node whose heartbeat went stale while it happened to be draining is
    # reported OFFLINE, not DRAINING — a stale row's status field isn't
    # trustworthy either.
    node = _node(status=BrowserNodeStatus.DRAINING, last_heartbeat=NOW - timedelta(minutes=5))
    assert compute_worker_health(node, now=NOW) == WorkerHealth.OFFLINE


def test_draining():
    assert compute_worker_health(_node(status=BrowserNodeStatus.DRAINING), now=NOW) == WorkerHealth.DRAINING


def test_self_reported_degraded():
    assert compute_worker_health(_node(status=BrowserNodeStatus.DEGRADED), now=NOW) == WorkerHealth.DEGRADED


def test_high_cpu_is_degraded():
    node = _node(cpu_percent=95.0)
    assert compute_worker_health(node, now=NOW) == WorkerHealth.DEGRADED


def test_high_ram_is_degraded():
    node = _node(ram_total_mb=1000, ram_used_mb=950)
    assert compute_worker_health(node, now=NOW) == WorkerHealth.DEGRADED


def test_missing_telemetry_never_computed_as_degraded():
    # No CPU/RAM data yet (a node that only just started reporting) must
    # never be treated as if it were pegged at 0% or 100% — it's simply not
    # a factor in the health decision until real numbers arrive.
    node = _node(cpu_percent=None, ram_total_mb=None, ram_used_mb=None)
    assert compute_worker_health(node, now=NOW) == WorkerHealth.HEALTHY


def test_uptime_computed_from_node_started_at():
    node = _node(node_started_at=NOW - timedelta(hours=2))
    assert worker_uptime_seconds(node, now=NOW) == 2 * 3600


def test_uptime_none_when_never_reported():
    node = _node(node_started_at=None)
    assert worker_uptime_seconds(node, now=NOW) is None
