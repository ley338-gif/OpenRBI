import uuid
from datetime import datetime

from pydantic import BaseModel


class CreatePolicyRequest(BaseModel):
    name: str
    policy_type: str


class FileRuleInput(BaseModel):
    rule_type: str  # "MIME" | "SOURCE"
    match_pattern: str
    action: str  # "AUTO_RELEASE" | "QUARANTINE" | "DENY"
    priority: int = 100


class CreateVersionRequest(BaseModel):
    content: dict = {}
    file_rules: list[FileRuleInput] = []


class RollbackRequest(BaseModel):
    version_id: uuid.UUID


class FileRuleResponse(BaseModel):
    id: uuid.UUID
    rule_type: str
    match_pattern: str
    action: str
    priority: int


class PolicyVersionResponse(BaseModel):
    id: uuid.UUID
    version_number: int
    status: str
    content: dict
    file_rules: list[FileRuleResponse]
    created_at: datetime
    published_at: datetime | None


class PolicySummary(BaseModel):
    id: uuid.UUID
    name: str
    policy_type: str
    description: str | None
    current_version_id: uuid.UUID | None
    current_version_number: int | None


class PolicyDetail(PolicySummary):
    versions: list[PolicyVersionResponse]
