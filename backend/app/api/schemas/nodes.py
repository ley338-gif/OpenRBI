import uuid
from datetime import datetime

from pydantic import BaseModel


class BrowserNodeResponse(BaseModel):
    id: uuid.UUID
    hostname: str
    status: str
    capacity: int
    active_sessions: int
    runtime: str
    version: str | None
    last_heartbeat: datetime | None

    @classmethod
    def from_model(cls, node) -> "BrowserNodeResponse":
        return cls(
            id=node.id,
            hostname=node.hostname,
            status=node.status.value,
            capacity=node.capacity,
            active_sessions=node.active_sessions,
            runtime=node.runtime,
            version=node.version,
            last_heartbeat=node.last_heartbeat,
        )
