from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.auth import CurrentUserResponse, LoginRequest, LoginResponse
from app.config import get_settings
from app.core.deps import get_current_user
from app.core.security import verify_password
from app.core.sessions import create_mfa_pending, create_session, delete_session
from app.db.session import get_db
from app.models.enums import SecurityEventType
from app.models.role import Role
from app.models.user import User
from app.services.security_events import record_security_event

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    """Fail closed: a nonexistent user, a disabled user, and a wrong password
    all produce the same generic 401 (no username enumeration), and every
    failure is recorded as USER_LOGIN_FAILED (docs/security-model.md).
    """
    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        await record_security_event(
            db,
            SecurityEventType.USER_LOGIN_FAILED,
            user_id=user.id if user is not None else None,
            metadata={"username": payload.username},
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    if user.mfa_enabled:
        # Password verified, but MFA (Phase 4) must still be satisfied before
        # a real session is issued — no partial-trust session is set here.
        mfa_token = await create_mfa_pending(user.id)
        return LoginResponse(status="mfa_required", mfa_token=mfa_token)

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
