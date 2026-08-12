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
            created_at=session.created_at,
            started_at=session.started_at,
            ended_at=session.ended_at,
        )


class AdminSessionResponse(SessionResponse):
    user_id: uuid.UUID
    username: str

    @classmethod
    def from_model_with_user(cls, session, username: str) -> "AdminSessionResponse":
        base = SessionResponse.from_model(session)
        return cls(**base.model_dump(), user_id=session.user_id, username=username)
