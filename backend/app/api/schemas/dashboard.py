from datetime import datetime

from pydantic import BaseModel


class DashboardKpisResponse(BaseModel):
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


class SessionHistoryPointResponse(BaseModel):
    t: datetime
    count: int


class WorkerSummaryResponse(BaseModel):
    id: str
    hostname: str
    health: str
    cpu_percent: float | None
    ram_percent: float | None
    active_sessions: int
    capacity: int


class DashboardWarningResponse(BaseModel):
    kind: str
    message: str
    worker_hostname: str | None
    username: str | None


class FileStatusSummaryResponse(BaseModel):
    status: str
    count: int


class RecentIncidentResponse(BaseModel):
    id: str
    severity: str
    status: str
    title: str
    created_at: datetime


class DashboardResponse(BaseModel):
    generated_at: datetime
    # True when at least one worker's heartbeat is stale (or there are no
    # workers reporting at all) — the frontend shows "Telemetry delayed"
    # instead of presenting the numbers as unquestionably current.
    telemetry_stale: bool
    kpis: DashboardKpisResponse
    session_history: list[SessionHistoryPointResponse]
    workers: list[WorkerSummaryResponse]
    warnings: list[DashboardWarningResponse]
    file_statuses_24h: list[FileStatusSummaryResponse]
    quarantine_pending: int
    quarantine_high_risk: int
    recent_incidents: list[RecentIncidentResponse]

    @classmethod
    def from_dashboard(cls, dashboard) -> "DashboardResponse":
        return cls(
            generated_at=dashboard.generated_at,
            telemetry_stale=dashboard.telemetry_stale,
            kpis=DashboardKpisResponse(**dashboard.kpis.__dict__),
            session_history=[SessionHistoryPointResponse(**p) for p in dashboard.session_history],
            workers=[WorkerSummaryResponse(**w.__dict__) for w in dashboard.workers],
            warnings=[DashboardWarningResponse(**w.__dict__) for w in dashboard.warnings],
            file_statuses_24h=[FileStatusSummaryResponse(**item.__dict__) for item in dashboard.file_statuses_24h],
            quarantine_pending=dashboard.quarantine_pending,
            quarantine_high_risk=dashboard.quarantine_high_risk,
            recent_incidents=[RecentIncidentResponse(**item.__dict__) for item in dashboard.recent_incidents],
        )
