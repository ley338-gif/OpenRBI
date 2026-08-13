import uuid
from datetime import datetime

from pydantic import BaseModel


class QuarantineFileResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    user_id: uuid.UUID
    original_name: str
    extension: str | None
    declared_mime: str | None
    detected_mime: str | None
    size_bytes: int
    sha256: str
    initial_url: str | None
    final_url: str | None
    source_host: str | None
    tls_used: bool | None
    scanner_status: str
    scanner_result: str | None
    policy_action: str | None
    status: str
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: uuid.UUID | None
    review_comment: str | None

    @classmethod
    def from_model(cls, qf) -> "QuarantineFileResponse":
        return cls(
            id=qf.id,
            session_id=qf.session_id,
            user_id=qf.user_id,
            original_name=qf.original_name,
            extension=qf.extension,
            declared_mime=qf.declared_mime,
            detected_mime=qf.detected_mime,
            size_bytes=qf.size_bytes,
            sha256=qf.sha256,
            initial_url=qf.initial_url,
            final_url=qf.final_url,
            source_host=qf.source_host,
            tls_used=qf.tls_used,
            scanner_status=qf.scanner_status.value,
            scanner_result=qf.scanner_result,
            policy_action=qf.policy_action.value if qf.policy_action else None,
            status=qf.status.value,
            created_at=qf.created_at,
            reviewed_at=qf.reviewed_at,
            reviewed_by=qf.reviewed_by,
            review_comment=qf.review_comment,
        )


class ReviewRequest(BaseModel):
    comment: str = ""


class DownloadTokenResponse(BaseModel):
    token: str
    expires_in_seconds: int


class UserFileSummary(BaseModel):
    total: int
    pending: int
    approved: int
    blocked: int


class UserFilePage(BaseModel):
    items: list[QuarantineFileResponse]
    summary: UserFileSummary
    total_filtered: int
    offset: int
    limit: int
