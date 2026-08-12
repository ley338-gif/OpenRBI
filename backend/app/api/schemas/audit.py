import uuid
from datetime import datetime

from pydantic import BaseModel


class SecurityEventResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    user_id: uuid.UUID | None
    session_id: uuid.UUID | None
    quarantine_file_id: uuid.UUID | None
    metadata_json: dict | None
    created_at: datetime

    @classmethod
    def from_model(cls, event) -> "SecurityEventResponse":
        return cls(
            id=event.id,
            event_type=event.event_type.value,
            user_id=event.user_id,
            session_id=event.session_id,
            quarantine_file_id=event.quarantine_file_id,
            metadata_json=event.metadata_json,
            created_at=event.created_at,
        )
