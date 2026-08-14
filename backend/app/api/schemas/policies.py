import uuid
from datetime import datetime

from pydantic import BaseModel


class CreatePolicyRequest(BaseModel):
    name: str
    policy_type: str
    description: str | None = None


class UpdatePolicyRequest(BaseModel):
    name: str
    description: str | None = None


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


class GroupRef(BaseModel):
    id: uuid.UUID
    name: str


class PolicySummary(BaseModel):
    id: uuid.UUID
    name: str
    policy_type: str
    description: str | None
    current_version_id: uuid.UUID | None
    current_version_number: int | None
    has_draft: bool = False
    version_count: int = 0
    assigned_groups: list[GroupRef] = []
    created_at: datetime
    updated_at: datetime
    updated_by: str | None = None


class PolicyStats(BaseModel):
    total: int
    published: int
    drafts: int
    in_use: int
    total_versions: int
    last_updated_at: datetime | None
    last_updated_by: str | None


class PolicyListResponse(BaseModel):
    items: list[PolicySummary]
    total: int
    offset: int
    limit: int
    stats: PolicyStats


class PolicyDetail(PolicySummary):
    versions: list[PolicyVersionResponse]


class PolicyRef(BaseModel):
    id: uuid.UUID
    name: str
    policy_type: str
