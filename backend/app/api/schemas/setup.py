from pydantic import BaseModel


class SetupStatusResponse(BaseModel):
    """Deliberately the only field — Section 13's explicit requirement:
    never leak existing usernames, LDAP config, or any other internal
    state through this unauthenticated endpoint.
    """

    setup_required: bool


class SetupAdminRequest(BaseModel):
    # No password-strength constraint here, deliberately matching
    # app/api/schemas/admin.py's CreateUserRequest exactly — the project
    # has no password policy anywhere yet (backend-enforced or otherwise),
    # and bootstrap must not invent a stricter or different rule of its
    # own ("keine Sonderimplementierung für Bootstrap-Passwörter").
    setup_token: str
    username: str
    password: str


class SetupAdminResponse(BaseModel):
    mfa_token: str


class SetupMfaConfirmRequest(BaseModel):
    mfa_token: str
    code: str


class SetupMfaConfirmResponse(BaseModel):
    status: str
    recovery_codes: list[str]
