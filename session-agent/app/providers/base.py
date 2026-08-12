"""SandboxProvider interface (see docs/adr/0003-provider-abstraction.md).

Core session-agent logic (the API layer) depends only on this interface,
never on docker-py directly, so a future GVisorSandboxProvider/
KataSandboxProvider can be swapped in via configuration without touching
the API. DockerSandboxProvider (docker_provider.py) is the first, required
implementation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class SandboxRuntimeStatus(str, Enum):
    """Raw provider-observed state, distinct from the control plane's
    BrowserSession FSM (docs/session-lifecycle.md) — the backend's Session
    Manager (Phase 10/11) maps this onto that FSM; the agent itself doesn't
    know about QUEUED/DISCONNECTED/etc.
    """

    NOT_FOUND = "NOT_FOUND"
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    ISOLATED = "ISOLATED"
    EXITED = "EXITED"
    ERROR = "ERROR"


@dataclass
class SandboxConfig:
    image: str
    cpu_limit: float
    ram_limit_mb: int
    pid_limit: int
    disk_limit_mb: int
    network_name: str
    command: list[str] | None = None
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class SandboxStatus:
    status: SandboxRuntimeStatus
    container_id: str | None = None
    started_at: str | None = None
    detail: str | None = None


@dataclass
class SandboxDisplayInfo:
    host: str
    port: int


@dataclass
class SandboxMetrics:
    cpu_percent: float
    memory_usage_mb: float
    memory_limit_mb: float
    pids: int


class SandboxProvider(Protocol):
    async def create_session(self, session_id: str, config: SandboxConfig) -> None: ...
    async def start_session(self, session_id: str) -> None: ...
    async def isolate_session(self, session_id: str) -> None: ...
    async def restore_session(self, session_id: str) -> None: ...
    async def terminate_session(self, session_id: str) -> None: ...
    async def get_status(self, session_id: str) -> SandboxStatus: ...
    async def get_metrics(self, session_id: str) -> SandboxMetrics: ...
    async def get_display_info(self, session_id: str) -> SandboxDisplayInfo: ...
