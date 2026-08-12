import uuid
from datetime import datetime

from pydantic import BaseModel


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


class CreateGroupRequest(BaseModel):
    name: str
    description: str | None = None


class GroupSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    member_count: int
