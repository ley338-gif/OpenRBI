import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.auth import CurrentUserResponse, LoginRequest, LoginResponse
from app.api.schemas.mfa import MfaVerifyRequest
from app.config import get_settings
from app.core.auth_providers.base import AuthResult
from app.core.auth_providers.factory import get_local_auth_provider
from app.core.auth_providers.ldap import LdapAuthProvider
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
from app.services.ldap_config_service import get_effective_ldap_config
from app.services.ldap_provisioning import resolve_or_provision_ldap_user
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

    Roadmap Phase B / B1.3: local is always tried first (fast, no network
    round-trip, and authoritative for any account with a real local
    password — docs/adr/0015). LDAP is only attempted if local fails *and*
    LDAP is currently enabled, and only one lockout/failure event is
    recorded per login attempt regardless of how many providers were
    tried, not one per provider — otherwise a single guessed password
    would burn through the lockout budget twice as fast.

    Roadmap B1.8: "currently enabled" is resolved per-request via
    get_effective_ldap_config — the admin-portal-configured database row
    if one exists, otherwise the original OPENRBI_LDAP_* env vars
    (docs/adr/0016) — rather than the module-level `settings` object,
    since LDAP can now be turned on/off and reconfigured at runtime
    without a backend restart.
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
    user: User | None = None

    if auth_result.success:
        user = await db.get(User, auth_result.matched_user_id)
    else:
        ldap_config = await get_effective_ldap_config(db)
        if ldap_config is not None:
            ldap_result: AuthResult = await LdapAuthProvider(ldap_config).authenticate(
                db, payload.username, payload.password
            )
            if ldap_result.success:
                user = await resolve_or_provision_ldap_user(db, payload.username, ldap_result.ldap_group_dns or [])

    if user is None:
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
    role = await db.get(Role, user.role_id)

    if user.mfa_enabled:
        # Password verified, but MFA must still be satisfied before a real
        # session is issued — no partial-trust session is set here. Commit
        # before returning: a JIT-provisioned LDAP user (Roadmap B1.3) may
        # still be only flush()ed, not committed, at this point — without
        # this the new row (and its USER_PROVISIONED_VIA_LDAP audit event)
        # would be silently discarded when the request's DB session closes,
        # and the mfa_token just issued would reference a user that was
        # never actually persisted. A pre-existing local account reaching
        # this branch has no pending writes, so this commit is a no-op for
        # it — safe either way.
        mfa_token = await create_mfa_pending(user.id)
        await db.commit()
        return LoginResponse(status="mfa_required", mfa_token=mfa_token)

    if role.name in _MFA_MANDATORY_ROLES:
        # MFA is mandatory for ADMIN/SECURITY_REVIEWER (docs/security-model.md)
        # — an account in this role with no TOTP enrolled yet must complete
        # enrollment before it ever gets a session, not after. Same commit
        # rationale as the branch above.
        mfa_token = await create_mfa_pending(user.id)
        await db.commit()
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
