from pydantic import BaseModel


class CreateSandboxRequest(BaseModel):
    session_id: str
    cpu_limit: float | None = None
    ram_limit_mb: int | None = None
    pid_limit: int | None = None
    disk_limit_mb: int | None = None
    image: str | None = None


class StatusResponse(BaseModel):
    status: str
    container_id: str | None = None
    started_at: str | None = None
    detail: str | None = None


class MetricsResponse(BaseModel):
    cpu_percent: float
    memory_usage_mb: float
    memory_limit_mb: float
    pids: int


class DisplayInfoResponse(BaseModel):
    host: str
    port: int
