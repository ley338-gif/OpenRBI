import uuid
from datetime import datetime

from pydantic import BaseModel


class SessionResponse(BaseModel):
    id: uuid.UUID
    status: str
    browser: str
    sandbox_backend: str
    display_backend: str
    cpu_limit: float
    ram_limit_mb: int
    pid_limit: int
    disk_limit_mb: int
    screen_width: int
    screen_height: int
    clipboard_mode: str
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None

    @classmethod
    def from_model(cls, session) -> "SessionResponse":
        return cls(
            id=session.id,
            status=session.status.value,
            browser=session.browser,
            sandbox_backend=session.sandbox_backend,
            display_backend=session.display_backend,
            cpu_limit=float(session.cpu_limit),
            ram_limit_mb=session.ram_limit_mb,
            pid_limit=session.pid_limit,
            disk_limit_mb=session.disk_limit_mb,
            screen_width=session.screen_width,
            screen_height=session.screen_height,
            clipboard_mode=session.clipboard_mode.value,
            created_at=session.created_at,
            started_at=session.started_at,
            ended_at=session.ended_at,
        )


class AdminSessionResponse(SessionResponse):
    user_id: uuid.UUID
    username: str
    node_id: uuid.UUID | None = None
    worker_hostname: str | None = None

    @classmethod
    def from_model_with_user(
        cls, session, username: str, worker_hostname: str | None = None
    ) -> "AdminSessionResponse":
        base = SessionResponse.from_model(session)
        return cls(
            **base.model_dump(),
            user_id=session.user_id,
            username=username,
            node_id=session.node_id,
            worker_hostname=worker_hostname,
        )


class SessionOperationsStats(BaseModel):
    active: int
    sessions_today: int
    average_duration_seconds_24h: float | None
    failed_24h: int
    terminated_24h: int


class SessionListResponse(BaseModel):
    items: list[AdminSessionResponse]
    total: int
    offset: int
    limit: int
    stats: SessionOperationsStats
    statuses: list[str]


class RevokeSessionsResponse(BaseModel):
    """Roadmap B1.10.4 — result of terminating every live session a user
    had. `session_ids` lets the caller confirm exactly which sessions were
    affected, not just a count."""

    terminated_count: int
    session_ids: list[uuid.UUID]
