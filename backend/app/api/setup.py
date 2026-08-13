"""Roadmap Phase B / B1.9 — first-run bootstrap API (docs/adr/
0017-first-run-bootstrap.md). Deliberately unauthenticated (there is no
admin yet) but closed by three independent layers: the persisted
system_state.initialized flag (never derived from COUNT(users)==0), the
console-only setup token, and the same per-key rate limiting
app/api/auth.py's login lockout uses. Registered only in an admin-capable
listener (app/main.py) — matches app/api/admin_ldap.py's placement, since
only the Admin Portal has any use for it.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.setup import (
    SetupAdminRequest,
    SetupAdminResponse,
    SetupMfaConfirmRequest,
    SetupMfaConfirmResponse,
    SetupStatusResponse,
)
from app.config import get_settings
from app.core.sessions import create_session, delete_mfa_pending, get_mfa_pending
from app.db.session import get_db
from app.models.user import User
from app.services.setup_service import (
    SetupAlreadyInitializedError,
    SetupError,
    SetupRateLimitedError,
    complete_bootstrap_mfa,
    create_bootstrap_admin,
    is_setup_required,
)

router = APIRouter(prefix="/setup", tags=["setup"])
settings = get_settings()


@router.get("/status", response_model=SetupStatusResponse)
async def status_endpoint(db: AsyncSession = Depends(get_db)) -> SetupStatusResponse:
    return SetupStatusResponse(setup_required=await is_setup_required(db))


@router.post("/admin", response_model=SetupAdminResponse)
async def create_admin(payload: SetupAdminRequest, db: AsyncSession = Depends(get_db)) -> SetupAdminResponse:
    try:
        mfa_token = await create_bootstrap_admin(
            db, setup_token=payload.setup_token, username=payload.username, password=payload.password
        )
    except SetupAlreadyInitializedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="system already initialized") from exc
    except SetupRateLimitedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many failed setup attempts"
        ) from exc
    except SetupError as exc:
        # Deliberately the same generic-enough message for "wrong token"
        # and "username taken" — SetupInvalidTokenError text and this
        # branch both stay a plain 400 with no internal detail, never a
        # stacktrace or a hint about which check failed.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="could not create the initial administrator") from exc
    return SetupAdminResponse(mfa_token=mfa_token)


@router.post("/mfa/confirm", response_model=SetupMfaConfirmResponse)
async def confirm_mfa(
    payload: SetupMfaConfirmRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> SetupMfaConfirmResponse:
    if not await is_setup_required(db):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="system already initialized")

    pending = await get_mfa_pending(payload.mfa_token)
    if pending is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired setup challenge")
    user = await db.get(User, uuid.UUID(pending["user_id"]))
    if user is None or not user.is_active:
        await delete_mfa_pending(payload.mfa_token)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired setup challenge")

    try:
        codes = await complete_bootstrap_mfa(db, mfa_token=payload.mfa_token, code=payload.code, user=user)
    except SetupAlreadyInitializedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="system already initialized") from exc
    except (SetupError, ValueError) as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid setup code") from exc

    await delete_mfa_pending(payload.mfa_token)

    session_token = await create_session(user.id, "ADMIN")
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
    )

    await db.commit()
    return SetupMfaConfirmResponse(status="ok", recovery_codes=codes)
