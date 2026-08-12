import uuid

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    status: str  # "ok" | "mfa_required"
    mfa_token: str | None = None


class CurrentUserResponse(BaseModel):
    id: uuid.UUID
    username: str
    role: str
    mfa_enabled: bool
