"""Roadmap Phase B / B1.9 — first-run bootstrap of the initial local
administrator (docs/adr/0017-first-run-bootstrap.md). Reuses, never
duplicates: app/services/users.py's create_user for account creation,
app/core/security.py's Argon2 hashing for both the admin's password and
the setup token, app/services/mfa.py's confirm_enrollment for TOTP
enrollment, app/core/sessions.py's create_session/create_mfa_pending/
is_login_locked-style rate limiting, and app/services/security_events.py
for audit.

Race-condition safety: both create_bootstrap_admin and
complete_bootstrap_mfa take out `SELECT ... FOR UPDATE` on the single
system_state row before reading or changing anything — a second,
concurrent request blocks until the first transaction commits, then sees
up-to-date state (already initialized, or the same in-progress admin) and
never creates a second admin or double-initializes the system.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.config import get_settings
from app.core.sessions import (
    clear_login_failures,
    create_mfa_pending,
    is_login_locked,
    record_login_failure,
)
from app.models.enums import SecurityEventType
from app.models.system_state import SYSTEM_STATE_ID, SystemState
from app.models.user import User
from app.services.mfa import confirm_enrollment
from app.services.security_events import record_security_event
from app.services.users import UserServiceError, create_user

# Bootstrap has no real username yet, so the existing per-username
# lockout/rate-limit machinery (app/core/sessions.py) is reused keyed by
# this fixed pseudo-username instead of adding a second brute-force guard.
_SETUP_TOKEN_RATE_LIMIT_KEY = "__setup_bootstrap__"

# Passed as create_user's created_by for the one account it can't have a
# real admin actor for — this is metadata only (stored as a string inside
# a security-event JSON blob, not a foreign key), so a fixed sentinel UUID
# is sufficient and never collides with a real user id in practice.
BOOTSTRAP_SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-0000005e7057")


class SetupError(ValueError):
    """Raised for any bootstrap validation/state failure; callers map this
    to the appropriate 4xx, never a silent partial success.
    """


class SetupAlreadyInitializedError(SetupError):
    pass


class SetupRateLimitedError(SetupError):
    pass


class SetupInvalidTokenError(SetupError):
    pass


async def _get_or_create_state(db: AsyncSession) -> SystemState:
    state = await db.get(SystemState, SYSTEM_STATE_ID)
    if state is None:
        state = SystemState(id=SYSTEM_STATE_ID, initialized=False)
        db.add(state)
        await db.flush()
    return state


async def _get_state_for_update(db: AsyncSession) -> SystemState:
    """Row-locks the single system_state row for the duration of the
    caller's transaction — the concurrency-safety primitive every bootstrap
    mutation in this module relies on.
    """
    await _get_or_create_state(db)  # ensures the row exists before locking it
    result = await db.execute(select(SystemState).where(SystemState.id == SYSTEM_STATE_ID).with_for_update())
    return result.scalar_one()


async def is_setup_required(db: AsyncSession) -> bool:
    state = await db.get(SystemState, SYSTEM_STATE_ID)
    return state is None or not state.initialized


async def regenerate_setup_token(db: AsyncSession) -> str | None:
    """Called once at backend startup (app/main.py) for an admin-capable
    listener. Regenerates and persists a fresh token every time the process
    starts while the system is still uninitialized — a lost/missed token is
    always recoverable by restarting the container, and a stale token from
    a previous boot is implicitly invalidated rather than left valid
    forever. Returns None (does nothing) once initialized, so the token
    stops being generated or logged at all after real setup completes.
    """
    state = await _get_state_for_update(db)
    if state.initialized:
        await db.commit()
        return None

    token = secrets.token_urlsafe(24)
    state.setup_token_hash = hash_password(token)
    state.setup_token_created_at = datetime.now(UTC)
    await db.commit()
    return token


async def create_bootstrap_admin(db: AsyncSession, *, setup_token: str, username: str, password: str) -> str:
    """Verifies the setup token, then creates (or, on retry, reuses) the
    single bootstrap admin account and returns a fresh mfa_token for the
    mandatory-MFA-enrollment step — the same Redis-backed pending-challenge
    mechanism app/api/auth.py's mfa_enrollment_required branch uses.
    """
    if await is_login_locked(_SETUP_TOKEN_RATE_LIMIT_KEY):
        raise SetupRateLimitedError("too many failed setup attempts")

    state = await _get_state_for_update(db)
    if state.initialized:
        await db.rollback()
        raise SetupAlreadyInitializedError("system already initialized")

    token_expires_at = (
        state.setup_token_created_at + timedelta(seconds=get_settings().setup_token_ttl_seconds)
        if state.setup_token_created_at is not None
        else None
    )
    token_is_expired = token_expires_at is None or datetime.now(UTC) >= token_expires_at
    if token_is_expired or state.setup_token_hash is None or not verify_password(setup_token, state.setup_token_hash):
        await db.rollback()
        await record_login_failure(_SETUP_TOKEN_RATE_LIMIT_KEY)
        raise SetupInvalidTokenError("invalid setup token")
    await clear_login_failures(_SETUP_TOKEN_RATE_LIMIT_KEY)

    if state.setup_admin_user_id is not None:
        # Retry: an earlier POST /setup/admin succeeded but MFA enrollment
        # was never completed (e.g. the browser closed mid-setup). Reuse
        # the same account — never create a second bootstrap admin — and
        # let this call update its username/password if the operator wants
        # to change either before finishing setup.
        user = await db.get(User, state.setup_admin_user_id)
    else:
        user = None

    if user is not None:
        existing = await db.execute(select(User).where(User.username == username, User.id != user.id))
        if existing.scalar_one_or_none() is not None:
            await db.rollback()
            raise SetupError(f"username already taken: {username}")
        user.username = username
        user.password_hash = hash_password(password)
        db.add(user)
        await db.flush()
    else:
        try:
            user = await create_user(
                db,
                username=username,
                password=password,
                role_name="ADMIN",
                group_ids=[],
                created_by=BOOTSTRAP_SYSTEM_ACTOR_ID,
            )
        except UserServiceError as exc:
            # A real bug, not a hypothetical: an entirely unrelated local
            # account already using this username (e.g. one created by a
            # prior, never-completed bootstrap attempt with a different
            # username reservation) previously propagated as an unhandled
            # 500 instead of the same clean "could not create the initial
            # administrator" 400 every other bootstrap failure returns.
            await db.rollback()
            raise SetupError(str(exc)) from exc
        state.setup_admin_user_id = user.id
        db.add(state)

    await record_security_event(
        db, SecurityEventType.INITIAL_ADMIN_CREATED, user_id=user.id, metadata={"username": username}
    )

    mfa_token = await create_mfa_pending(user.id)
    await db.commit()
    return mfa_token


async def complete_bootstrap_mfa(db: AsyncSession, *, mfa_token: str, code: str, user: User) -> list[str]:
    """Completes the bootstrap flow: verifies the TOTP code (reusing
    app/services/mfa.py's confirm_enrollment unchanged), then — in the same
    transaction — marks the system permanently initialized. `user` is
    resolved and ownership-checked by the caller (app/api/setup.py), which
    also deletes the mfa_token afterward, mirroring app/api/mfa.py's
    setup_confirm exactly.
    """
    state = await _get_state_for_update(db)
    if state.initialized:
        await db.rollback()
        raise SetupAlreadyInitializedError("system already initialized")
    if state.setup_admin_user_id != user.id:
        # Guards against a stray/unrelated mfa_token being used to trigger
        # SYSTEM_INITIALIZED for a user that isn't actually this
        # installation's bootstrap admin.
        await db.rollback()
        raise SetupError("mfa_token does not belong to the bootstrap admin")

    codes = await confirm_enrollment(db, user, code)  # raises ValueError on a wrong code

    state.initialized = True
    state.initialized_at = datetime.now(UTC)
    state.setup_token_hash = None
    state.setup_token_created_at = None
    db.add(state)

    await record_security_event(db, SecurityEventType.SYSTEM_INITIALIZED, user_id=user.id)
    return codes
