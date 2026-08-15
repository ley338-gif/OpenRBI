import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret
from app.core.recovery_codes import generate_recovery_codes
from app.core.security import hash_password, verify_password
from app.core.sessions import revoke_all_sessions_for_user
from app.core.totp import verify_code
from app.models.enums import SecurityEventType
from app.models.mfa import RecoveryCode
from app.models.user import User
from app.services.security_events import record_security_event


async def confirm_enrollment(db: AsyncSession, user: User, code: str) -> list[str]:
    """Verifies the TOTP code against the pending (already-stored, not yet
    enabled) secret. On success: enables MFA, replaces any old recovery
    codes, and returns the new plaintext codes (shown once — only their
    hashes are persisted).
    """
    if user.totp_secret_encrypted is None:
        raise ValueError("no pending TOTP enrollment")

    secret = decrypt_secret(user.totp_secret_encrypted)
    if not verify_code(secret, code):
        raise ValueError("invalid TOTP code")

    user.mfa_enabled = True
    db.add(user)

    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    plaintext_codes = generate_recovery_codes()
    for plaintext in plaintext_codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=hash_password(plaintext)))

    await record_security_event(db, SecurityEventType.MFA_ENROLLED, user_id=user.id)
    await db.flush()
    return plaintext_codes


async def verify_login_factor(db: AsyncSession, user: User, code: str) -> bool:
    """Accepts either a live TOTP code or an unused recovery code. Fails
    closed on any decryption/lookup error rather than raising past the
    caller as a 500 (docs/adr/0008-fail-closed.md).
    """
    if user.totp_secret_encrypted is not None:
        try:
            secret = decrypt_secret(user.totp_secret_encrypted)
        except ValueError:
            secret = None
        if secret and verify_code(secret, code):
            return True

    # RBI-POST-015: FOR UPDATE closes a check-then-update race — without
    # it, two concurrent requests replaying the same recovery code could
    # both SELECT the still-unused row and both pass verify_password()
    # before either commits its used_at write, redeeming the same
    # single-use code twice. Postgres blocks the second transaction's
    # SELECT ... FOR UPDATE on this row until the first commits, then
    # (READ COMMITTED's documented FOR UPDATE behavior) re-fetches the
    # row's now-current data — so the second pass sees used_at already
    # set and correctly treats the code as already spent, matching the
    # exact-once redemption guarantee this exists to make real rather
    # than merely likely.
    result = await db.execute(
        select(RecoveryCode)
        .where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))
        .with_for_update()
    )
    for recovery_code in result.scalars():
        if verify_password(code, recovery_code.code_hash):
            recovery_code.used_at = datetime.now(UTC)
            db.add(recovery_code)
            await record_security_event(db, SecurityEventType.RECOVERY_CODE_USED, user_id=user.id)
            return True

    return False


async def reset_mfa(db: AsyncSession, target_user: User, admin_user_id: uuid.UUID) -> None:
    """Never returns or logs the old TOTP secret — it's simply discarded.
    Roadmap B1.10.5: also revokes every one of the user's active login
    sessions, so a reset triggered by a suspected compromise (lost device,
    etc.) takes effect immediately rather than leaving an already-issued
    session valid until it naturally expires — MFA is otherwise only
    re-checked at login time, not on every request.
    """
    target_user.mfa_enabled = False
    target_user.totp_secret_encrypted = None
    db.add(target_user)
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == target_user.id))
    revoked = await revoke_all_sessions_for_user(target_user.id)
    await record_security_event(
        db,
        SecurityEventType.MFA_RESET,
        user_id=target_user.id,
        metadata={"reset_by": str(admin_user_id), "sessions_revoked": revoked},
    )
    await db.flush()
