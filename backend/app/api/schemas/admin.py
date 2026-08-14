import uuid
from datetime import datetime

from pydantic import BaseModel

from app.api.schemas.policies import PolicyRef


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
    groups: list[str]
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
    """Roadmap B1.10.5/B1.10.6 — the same brute-force-lockout state
    /auth/login itself checks, surfaced read-only for User Detail and
    Login Diagnostics."""

    locked: bool
    failure_count: int
    locked_seconds_remaining: int | None


class RecentFailedAttempt(BaseModel):
    event_type: str
    created_at: datetime


class LoginDiagnosticsResponse(BaseModel):
    """Roadmap B1.10.6 — read-only "why can't this user log in?" summary.
    Never includes a password check or any secret; every field here is a
    signal /auth/login itself already evaluates.
    """

    username: str
    user_id: uuid.UUID | None
    account_exists: bool
    is_active: bool | None
    mfa_enabled: bool | None
    auth_source: str | None
    ldap_enabled: bool
    lockout: LockoutStatus
    recent_failed_attempts: list[RecentFailedAttempt]
    possible_reasons: list[str]


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


class GroupDetail(GroupSummary):
    created_at: datetime
    policies: list[PolicyRef]


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
