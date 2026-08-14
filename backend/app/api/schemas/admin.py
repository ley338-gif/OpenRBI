import uuid
from datetime import datetime

from pydantic import BaseModel

from app.api.schemas.policies import GroupRef, PolicyRef


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str
    group_ids: list[uuid.UUID] = []


class UpdateUserRoleRequest(BaseModel):
    role: str


class ResetPasswordRequest(BaseModel):
    new_password: str


class SetUserGroupsRequest(BaseModel):
    group_ids: list[uuid.UUID]


class UserSummary(BaseModel):
    id: uuid.UUID
    username: str
    role: str
    is_active: bool
    mfa_enabled: bool
    groups: list[GroupRef]
    created_at: datetime
    auth_source: str
    last_login_at: datetime | None


class UserManagementStats(BaseModel):
    total: int
    active: int
    mfa_enabled: int
    administrators: int
    groups: int


class UserListResponse(BaseModel):
    items: list[UserSummary]
    total: int
    offset: int
    limit: int
    stats: UserManagementStats
    roles: list[str]


class LockoutStatus(BaseModel):
    """Roadmap B1.10.5 — the same brute-force-lockout state /auth/login
    itself checks, surfaced read-only for User Detail's Lock/Unlock
    controls."""

    locked: bool
    failure_count: int
    locked_seconds_remaining: int | None


class CreateGroupRequest(BaseModel):
    name: str
    description: str | None = None


class GroupSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    member_count: int


class GroupOverviewItem(GroupSummary):
    policies: list[str]
    created_at: datetime


class UserRef(BaseModel):
    id: uuid.UUID
    username: str


class GroupDetail(GroupSummary):
    created_at: datetime
    policies: list[PolicyRef]
    members: list[UserRef]


class GroupOverviewStats(BaseModel):
    total: int
    memberships: int
    with_policies: int


class GroupOverviewResponse(BaseModel):
    items: list[GroupOverviewItem]
    total: int
    offset: int
    limit: int
    stats: GroupOverviewStats
