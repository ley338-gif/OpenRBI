import uuid
from datetime import datetime

from pydantic import BaseModel


class IncidentResponse(BaseModel):
    id: uuid.UUID
    severity: str
    status: str
    title: str
    description: str
    user_id: uuid.UUID | None
    session_id: uuid.UUID | None
    quarantine_file_id: uuid.UUID | None
    assigned_to: uuid.UUID | None
    resolution: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, incident) -> "IncidentResponse":
        return cls(
            id=incident.id,
            severity=incident.severity.value,
            status=incident.status.value,
            title=incident.title,
            description=incident.description,
            user_id=incident.user_id,
            session_id=incident.session_id,
            quarantine_file_id=incident.quarantine_file_id,
            assigned_to=incident.assigned_to,
            resolution=incident.resolution,
            created_at=incident.created_at,
            updated_at=incident.updated_at,
        )


class UpdateIncidentRequest(BaseModel):
    status: str | None = None
    assigned_to: uuid.UUID | None = None
    resolution: str | None = None
