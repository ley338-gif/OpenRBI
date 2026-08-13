import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.mfa import (
    EnrollConfirmRequest,
    EnrollConfirmResponse,
    SelfResetRequest,
    EnrollResponse,
    SetupConfirmRequest,
    SetupConfirmResponse,
    SetupEnrollRequest,
)
from app.config import get_settings
from app.core.crypto import encrypt_secret
from app.core.deps import get_current_user
from app.core.qrcode_util import png_data_uri
from app.core.sessions import create_session, delete_mfa_pending, get_mfa_pending
from app.core.totp import generate_secret, provisioning_uri
from app.db.session import get_db
from app.models.enums import SecurityEventType
from app.models.role import Role
from app.models.user import User
from app.services.mfa import confirm_enrollment, reset_mfa, verify_login_factor
from app.services.security_events import record_security_event

# Shared/user-facing MFA: enrollment and mandatory-setup for any role,
# including ADMIN/SECURITY_REVIEWER's own first-time enrollment (see
# setup_enroll/setup_confirm below) — registered in every listener mode
# (Productization v0.1.1, docs/adr/0011-user-admin-listener-separation.md).
# The one admin-*on-someone-else's-account* endpoint that used to live here
# (MFA reset) moved to app/api/admin_mfa.py, admin-only, so it doesn't force
# an admin route into a user-mode listener.
router = APIRouter(prefix="/mfa", tags=["mfa"])
settings = get_settings()


async def _load_pending_user(db: AsyncSession, mfa_token: str) -> User:
    pending = await get_mfa_pending(mfa_token)
    if pending is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired MFA challenge")
    user = await db.get(User, uuid.UUID(pending["user_id"]))
    if user is None or not user.is_active:
        await delete_mfa_pending(mfa_token)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired MFA challenge")
    return user


@router.post("/enroll", response_model=EnrollResponse)
async def enroll(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EnrollResponse:
    """Voluntary enrollment for a user already holding a full session (USER
    role, or any role that already logged in before MFA was made mandatory
    for it). Mandatory first-time enrollment for ADMIN/SECURITY_REVIEWER
    uses /mfa/setup/enroll instead, since those accounts never get a full
    session until MFA is set up.
    """
    if current_user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="MFA already enabled")

    secret = generate_secret()
    current_user.totp_secret_encrypted = encrypt_secret(secret)
    db.add(current_user)
    await db.commit()

    uri = provisioning_uri(secret, current_user.username)
    return EnrollResponse(otpauth_uri=uri, qr_code_png_base64=png_data_uri(uri))


@router.post("/enroll/confirm", response_model=EnrollConfirmResponse)
async def enroll_confirm(
    payload: EnrollConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EnrollConfirmResponse:
    if current_user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="MFA already enabled")

    try:
        codes = await confirm_enrollment(db, current_user, payload.code)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.commit()
    return EnrollConfirmResponse(recovery_codes=codes)


@router.post("/setup/enroll", response_model=EnrollResponse)
async def setup_enroll(payload: SetupEnrollRequest, db: AsyncSession = Depends(get_db)) -> EnrollResponse:
    """Mandatory-enrollment path for a user in an MFA-mandatory role who
    passed the password check but has no session yet (see
    app/api/auth.py's mfa_enrollment_required branch).
    """
    user = await _load_pending_user(db, payload.mfa_token)
    if user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="MFA already enabled")

    secret = generate_secret()
    user.totp_secret_encrypted = encrypt_secret(secret)
    db.add(user)
    await db.commit()

    uri = provisioning_uri(secret, user.username)
    return EnrollResponse(otpauth_uri=uri, qr_code_png_base64=png_data_uri(uri))


@router.post("/setup/confirm", response_model=SetupConfirmResponse)
async def setup_confirm(
    payload: SetupConfirmRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> SetupConfirmResponse:
    user = await _load_pending_user(db, payload.mfa_token)
    if user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="MFA already enabled")

    try:
        codes = await confirm_enrollment(db, user, payload.code)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

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
    return SetupConfirmResponse(status="ok", recovery_codes=codes)
@router.post("/reset-self")
async def reset_self(
    payload: SelfResetRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if not current_user.mfa_enabled or not await verify_login_factor(db, current_user, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid authentication code")
    await reset_mfa(db, current_user, current_user.id)
    await db.commit()
    response.delete_cookie(settings.session_cookie_name)
    return {"status": "ok"}
