"""Roadmap Phase B / B1.10.2 — the single dashboard-aggregation service
backing GET /admin/dashboard. Reuses, never re-derives: app/services/
health.py's get_system_health() for the System Health KPI,
app/services/worker_health.py's compute_worker_health() for per-worker
health, app/services/metrics_history.py for the session-history graph.
Only sensible KPIs, per the task's own "no vanity metrics" instruction —
nothing here is fabricated or interpolated when data is missing; a
worker's cpu_percent being None (never reported yet) is excluded from the
average, not treated as 0.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.browser_node import BrowserNode
from app.models.browser_session import BrowserSession
from app.models.enums import IncidentSeverity, IncidentStatus, QuarantineStatus, SecurityEventType, SessionStatus
from app.models.incident import Incident
from app.models.quarantine import QuarantineFile
from app.models.security_event import SecurityEvent
from app.models.user import User
from app.models.worker_metric_sample import WorkerMetricSample
from app.services import metrics_history
from app.services.health import ComponentStatus, get_system_health
from app.services.worker_health import WorkerHealth, compute_worker_health, is_heartbeat_stale

_ACTIVE_SESSION_STATUSES = (SessionStatus.ACTIVE, SessionStatus.DISCONNECTED)

# A worker whose CPU has stayed at/above the degraded threshold for at
# least this long generates a dashboard warning — a single noisy sample
# doesn't (the task's own "no complex alerting platform" instruction: a
# handful of clearly-defined, real conditions, not a rules engine).
_SUSTAINED_HIGH_LOAD_WINDOW = timedelta(minutes=10)
_FAILED_LOGIN_WARNING_WINDOW = timedelta(minutes=15)
_FAILED_LOGIN_WARNING_THRESHOLD = 3


@dataclass
class WorkerSummary:
    id: str
    hostname: str
    health: str
    cpu_percent: float | None
    ram_percent: float | None
    active_sessions: int
    capacity: int


@dataclass
class Warning:
    kind: str
    message: str
    worker_hostname: str | None = None
    username: str | None = None


@dataclass
class DashboardKpis:
    active_sessions: int
    active_sessions_delta_last_hour: int | None
    workers_healthy: int
    workers_total: int
    system_health: str
    avg_cpu_percent: float | None
    avg_ram_percent: float | None
    users: int
    files_processed_24h: int
    blocked_files_24h: int
    incidents_24h: int


@dataclass
class FileStatusSummary:
    status: str
    count: int


@dataclass
class RecentIncident:
    id: str
    severity: str
    status: str
    title: str
    created_at: datetime


@dataclass
class Dashboard:
    generated_at: datetime
    telemetry_stale: bool
    kpis: DashboardKpis
    session_history: list[dict]
    workers: list[WorkerSummary]
    warnings: list[Warning]
    file_statuses_24h: list[FileStatusSummary]
    quarantine_pending: int
    quarantine_high_risk: int
    recent_incidents: list[RecentIncident]


async def _active_sessions_delta_last_hour(db: AsyncSession, *, now: datetime) -> int | None:
    an_hour_ago = now - timedelta(hours=1)

    # None (not 0) when there's no way to know yet — a fresh install with
    # no session history that old shouldn't claim "+0 last hour" as if
    # that were a measured fact.
    oldest = await db.execute(select(BrowserSession.started_at).order_by(BrowserSession.started_at).limit(1))
    earliest = oldest.scalar_one_or_none()
    if earliest is None or earliest > an_hour_ago:
        return None

    result = await db.execute(
        select(BrowserSession.id).where(
            BrowserSession.started_at.is_not(None),
            BrowserSession.started_at <= an_hour_ago,
            (BrowserSession.ended_at.is_(None)) | (BrowserSession.ended_at > an_hour_ago),
        )
    )
    return len(result.scalars().all())


def _sustained_high_load_warnings(nodes: list[BrowserNode], samples_by_node: dict) -> list[Warning]:
    settings = get_settings()
    warnings: list[Warning] = []
    for node in nodes:
        samples = samples_by_node.get(node.id, [])
        recent = [s for s in samples if s.cpu_percent is not None]
        if len(recent) < 2:
            continue
        if all(s.cpu_percent >= settings.node_cpu_degraded_percent for s in recent):
            warnings.append(
                Warning(
                    kind="high_cpu",
                    worker_hostname=node.hostname,
                    message=f"{node.hostname} CPU above {settings.node_cpu_degraded_percent:.0f}% for over {int(_SUSTAINED_HIGH_LOAD_WINDOW.total_seconds() / 60)} minutes",
                )
            )
    return warnings


async def get_dashboard(db: AsyncSession, *, range_key: str = "24h") -> Dashboard:
    now = datetime.now(UTC)
    settings = get_settings()

    result = await db.execute(select(BrowserSession.status))
    all_statuses = result.scalars().all()
    active_sessions = sum(1 for s in all_statuses if s in _ACTIVE_SESSION_STATUSES)

    since_24h = now - timedelta(hours=24)
    users = await db.scalar(select(func.count(User.id))) or 0
    file_status_result = await db.execute(
        select(QuarantineFile.status, func.count(QuarantineFile.id))
        .where(QuarantineFile.created_at >= since_24h)
        .group_by(QuarantineFile.status)
    )
    file_status_counts = {status: count for status, count in file_status_result.all()}
    files_processed_24h = sum(file_status_counts.values())
    blocked_files_24h = file_status_counts.get(QuarantineStatus.REJECTED, 0)
    incidents_24h = await db.scalar(select(func.count(Incident.id)).where(Incident.created_at >= since_24h)) or 0
    quarantine_pending = await db.scalar(
        select(func.count(QuarantineFile.id)).where(QuarantineFile.status == QuarantineStatus.QUARANTINED)
    ) or 0
    quarantine_high_risk = await db.scalar(
        select(func.count(Incident.id)).where(
            Incident.quarantine_file_id.is_not(None),
            Incident.severity.in_((IncidentSeverity.HIGH, IncidentSeverity.CRITICAL)),
            Incident.status.in_((IncidentStatus.NEW, IncidentStatus.INVESTIGATING)),
        )
    ) or 0
    recent_incident_result = await db.execute(select(Incident).order_by(Incident.created_at.desc()).limit(5))
    recent_incidents = [
        RecentIncident(
            id=str(incident.id),
            severity=incident.severity.value,
            status=incident.status.value,
            title=incident.title,
            created_at=incident.created_at,
        )
        for incident in recent_incident_result.scalars()
    ]

    nodes_result = await db.execute(select(BrowserNode))
    nodes = list(nodes_result.scalars().all())

    workers: list[WorkerSummary] = []
    cpu_values: list[float] = []
    ram_percent_values: list[float] = []
    healthy_count = 0
    any_stale = len(nodes) == 0
    node_health: dict = {}
    for node in nodes:
        health = compute_worker_health(node, now=now)
        node_health[node.id] = health
        if health == WorkerHealth.HEALTHY:
            healthy_count += 1
        if is_heartbeat_stale(node, now=now):
            any_stale = True
        ram_percent = None
        if node.ram_total_mb and node.ram_used_mb is not None and node.ram_total_mb > 0:
            ram_percent = round((node.ram_used_mb / node.ram_total_mb) * 100, 1)
            ram_percent_values.append(ram_percent)
        if node.cpu_percent is not None:
            cpu_values.append(node.cpu_percent)
        workers.append(
            WorkerSummary(
                id=str(node.id),
                hostname=node.hostname,
                health=health.value,
                cpu_percent=node.cpu_percent,
                ram_percent=ram_percent,
                active_sessions=node.active_sessions,
                capacity=node.capacity,
            )
        )

    system_health = await get_system_health(db)

    # Sustained-high-CPU check: pull each node's samples from the last
    # _SUSTAINED_HIGH_LOAD_WINDOW directly (cheap — a handful of rows per
    # node at a 15s poll interval), not from the full requested range.
    samples_by_node: dict = {}
    if nodes:
        since = now - _SUSTAINED_HIGH_LOAD_WINDOW
        sample_result = await db.execute(select(WorkerMetricSample).where(WorkerMetricSample.recorded_at >= since))
        for sample in sample_result.scalars():
            samples_by_node.setdefault(sample.node_id, []).append(sample)

    warnings = _sustained_high_load_warnings(nodes, samples_by_node)
    for node in nodes:
        health = node_health[node.id]
        if health == WorkerHealth.DRAINING:
            warnings.append(Warning(kind="draining", worker_hostname=node.hostname, message=f"{node.hostname} is draining"))
        elif health == WorkerHealth.MAINTENANCE:
            warnings.append(
                Warning(kind="maintenance", worker_hostname=node.hostname, message=f"{node.hostname} is in maintenance")
            )
        elif health == WorkerHealth.OFFLINE:
            warnings.append(Warning(kind="offline", worker_hostname=node.hostname, message=f"{node.hostname} is offline"))

    since_failed = now - _FAILED_LOGIN_WARNING_WINDOW
    failed_result = await db.execute(
        select(SecurityEvent.metadata_json).where(
            SecurityEvent.event_type == SecurityEventType.USER_LOGIN_FAILED,
            SecurityEvent.created_at >= since_failed,
        )
    )
    failed_counts: dict[str, int] = {}
    for (metadata,) in failed_result.all():
        username = (metadata or {}).get("username")
        if username:
            failed_counts[username] = failed_counts.get(username, 0) + 1
    for username, count in failed_counts.items():
        if count >= _FAILED_LOGIN_WARNING_THRESHOLD:
            warnings.append(
                Warning(kind="failed_logins", username=username, message=f"{count} failed login attempts for user {username}")
            )

    history = await metrics_history.session_history(db, range_key=range_key, now=now)

    return Dashboard(
        generated_at=now,
        telemetry_stale=any_stale,
        kpis=DashboardKpis(
            active_sessions=active_sessions,
            active_sessions_delta_last_hour=await _active_sessions_delta_last_hour(db, now=now),
            workers_healthy=healthy_count,
            workers_total=len(nodes),
            system_health=system_health.status.value,
            avg_cpu_percent=round(sum(cpu_values) / len(cpu_values), 1) if cpu_values else None,
            avg_ram_percent=round(sum(ram_percent_values) / len(ram_percent_values), 1) if ram_percent_values else None,
            users=users,
            files_processed_24h=files_processed_24h,
            blocked_files_24h=blocked_files_24h,
            incidents_24h=incidents_24h,
        ),
        session_history=history,
        workers=workers,
        warnings=warnings,
        file_statuses_24h=[
            FileStatusSummary(status=status.value, count=file_status_counts.get(status, 0))
            for status in QuarantineStatus
            if file_status_counts.get(status, 0) > 0
        ],
        quarantine_pending=quarantine_pending,
        quarantine_high_risk=quarantine_high_risk,
        recent_incidents=recent_incidents,
    )
