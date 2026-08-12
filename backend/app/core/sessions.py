import json
import secrets
import uuid

from app.config import get_settings
from app.core.redis import get_redis

_SESSION_PREFIX = "session:"
_MFA_PENDING_PREFIX = "mfa_pending:"
_MFA_PENDING_TTL_SECONDS = 5 * 60
_MFA_PENDING_MAX_ATTEMPTS = 5


async def create_session(user_id: uuid.UUID, role: str) -> str:
    """Full, MFA-satisfied session. Server-side state in Redis (not a JWT) so
    an admin Kill/Disconnect/disable-user action can revoke it immediately —
    see docs/security-model.md.
    """
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    redis_client = get_redis()
    await redis_client.set(
        f"{_SESSION_PREFIX}{token}",
        json.dumps({"user_id": str(user_id), "role": role}),
        ex=settings.session_ttl_seconds,
    )
    return token


async def get_session(token: str) -> dict | None:
    if not token:
        return None
    redis_client = get_redis()
    raw = await redis_client.get(f"{_SESSION_PREFIX}{token}")
    if raw is None:
        return None
    return json.loads(raw)


async def delete_session(token: str) -> None:
    redis_client = get_redis()
    await redis_client.delete(f"{_SESSION_PREFIX}{token}")


async def create_mfa_pending(user_id: uuid.UUID) -> str:
    """Short-lived pre-auth state for a user whose password check passed but
    who still needs to satisfy TOTP (Phase 4 verifies and upgrades this to a
    real session). Never usable as a session token on its own.
    """
    token = secrets.token_urlsafe(32)
    redis_client = get_redis()
    await redis_client.set(
        f"{_MFA_PENDING_PREFIX}{token}",
        json.dumps({"user_id": str(user_id), "attempts": 0}),
        ex=_MFA_PENDING_TTL_SECONDS,
    )
    return token


async def get_mfa_pending(token: str) -> dict | None:
    if not token:
        return None
    redis_client = get_redis()
    raw = await redis_client.get(f"{_MFA_PENDING_PREFIX}{token}")
    if raw is None:
        return None
    return json.loads(raw)


async def delete_mfa_pending(token: str) -> None:
    redis_client = get_redis()
    await redis_client.delete(f"{_MFA_PENDING_PREFIX}{token}")


async def record_mfa_pending_failure(token: str) -> bool:
    """Returns True if the pending token is still usable, False if it just
    got invalidated for exceeding the attempt limit (brute-force guard on a
    5-minute window against a 6-digit code — see docs/security-model.md).
    """
    pending = await get_mfa_pending(token)
    if pending is None:
        return False
    attempts = pending.get("attempts", 0) + 1
    if attempts >= _MFA_PENDING_MAX_ATTEMPTS:
        await delete_mfa_pending(token)
        return False
    redis_client = get_redis()
    ttl = await redis_client.ttl(f"{_MFA_PENDING_PREFIX}{token}")
    await redis_client.set(
        f"{_MFA_PENDING_PREFIX}{token}",
        json.dumps({**pending, "attempts": attempts}),
        ex=ttl if ttl and ttl > 0 else _MFA_PENDING_TTL_SECONDS,
    )
    return True
