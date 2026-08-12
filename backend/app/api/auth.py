import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.auth import CurrentUserResponse, LoginRequest, LoginResponse
from app.api.schemas.mfa import MfaVerifyRequest
from app.config import get_settings
from app.core.auth_providers.factory import get_local_auth_provider
from app.core.deps import get_current_user
from app.core.sessions import (
    clear_login_failures,
    create_mfa_pending,
    create_session,
    delete_mfa_pending,
    delete_session,
    get_mfa_pending,
    is_login_locked,
    record_login_failure,
    record_mfa_pending_failure,
)
from app.db.session import get_db
from app.models.enums import SecurityEventType
from app.models.role import Role
from app.models.user import User
from app.services.mfa import verify_login_factor
from app.services.security_events import record_security_event

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

_MFA_MANDATORY_ROLES = ("ADMIN", "SECURITY_REVIEWER")


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    """Fail closed: a nonexistent user, a disabled user, and a wrong password
    all produce the same generic 401 (no username enumeration), and every
    failure is recorded as USER_LOGIN_FAILED (docs/security-model.md).

    Also fails closed against unlimited online password guessing (Phase 20
    hardening): a username with too many recent failures is locked out for
    the rest of the window and gets the same generic response shape (429,
    not a distinct error), so this can't be used to enumerate usernames
    either.
    """
    if await is_login_locked(payload.username):
        await record_security_event(
            db, SecurityEventType.LOGIN_LOCKED, metadata={"username": payload.username}
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many failed login attempts"
        )

    auth_result = await get_local_auth_provider().authenticate(db, payload.username, payload.password)

    if not auth_result.success:
        await record_login_failure(payload.username)
        await record_security_event(
            db,
            SecurityEventType.USER_LOGIN_FAILED,
            user_id=auth_result.matched_user_id,
            metadata={"username": payload.username},
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    await clear_login_failures(payload.username)
    user = await db.get(User, auth_result.matched_user_id)
    role = await db.get(Role, user.role_id)

    if user.mfa_enabled:
        # Password verified, but MFA must still be satisfied before a real
        # session is issued — no partial-trust session is set here.
        mfa_token = await create_mfa_pending(user.id)
        return LoginResponse(status="mfa_required", mfa_token=mfa_token)

    if role.name in _MFA_MANDATORY_ROLES:
        # MFA is mandatory for ADMIN/SECURITY_REVIEWER (docs/security-model.md)
        # — an account in this role with no TOTP enrolled yet must complete
        # enrollment before it ever gets a session, not after.
        mfa_token = await create_mfa_pending(user.id)
        return LoginResponse(status="mfa_enrollment_required", mfa_token=mfa_token)

    session_token = await create_session(user.id, role.name)
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
    )

    await record_security_event(db, SecurityEventType.USER_LOGIN, user_id=user.id)
    await db.commit()
    return LoginResponse(status="ok")


@router.post("/logout")
async def logout(
    response: Response,
    current_user: User = Depends(get_current_user),
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> dict[str, str]:
    if session_token is not None:
        await delete_session(session_token)
    response.delete_cookie(settings.session_cookie_name)
    return {"status": "ok"}


@router.get("/me", response_model=CurrentUserResponse)
async def me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> CurrentUserResponse:
    role = await db.get(Role, current_user.role_id)
    return CurrentUserResponse(
        id=current_user.id,
        username=current_user.username,
        role=role.name,
        mfa_enabled=current_user.mfa_enabled,
    )


@router.post("/mfa/verify", response_model=LoginResponse)
async def mfa_verify(
    payload: MfaVerifyRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> LoginResponse:
    """Completes a login for a user who already has MFA enrolled (the
    mfa_enrollment_required path uses /mfa/setup/confirm instead — see
    app/api/mfa.py). Fails closed: an invalid/expired mfa_token, an already
    over-attempted one, or a wrong code are all the same generic 401.
    """
    pending = await get_mfa_pending(payload.mfa_token)
    if pending is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired MFA challenge")

    user = await db.get(User, uuid.UUID(pending["user_id"]))
    if user is None or not user.is_active or not user.mfa_enabled:
        await delete_mfa_pending(payload.mfa_token)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired MFA challenge")

    if not await verify_login_factor(db, user, payload.code):
        await record_security_event(db, SecurityEventType.MFA_FAILED, user_id=user.id)
        await db.commit()
        still_valid = await record_mfa_pending_failure(payload.mfa_token)
        detail = "invalid MFA code" if still_valid else "too many failed attempts, please log in again"
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)

    await delete_mfa_pending(payload.mfa_token)

    role = await db.get(Role, user.role_id)
    session_token = await create_session(user.id, role.name)
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
    )

    await record_security_event(db, SecurityEventType.USER_LOGIN, user_id=user.id)
    await db.commit()
    return LoginResponse(status="ok")
