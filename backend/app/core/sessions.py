import json
import secrets
import uuid

from app.config import get_settings
from app.core.redis import get_redis

_SESSION_PREFIX = "session:"
_MFA_PENDING_PREFIX = "mfa_pending:"
_MFA_PENDING_TTL_SECONDS = 5 * 60
_MFA_PENDING_MAX_ATTEMPTS = 5

_LOGIN_FAILURE_PREFIX = "login_fail:"
_LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
_LOGIN_FAILURE_MAX_ATTEMPTS = 10


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


async def revoke_all_sessions_for_user(user_id: uuid.UUID) -> int:
    """Roadmap B1.10.5 — deletes every server-side login session belonging
    to this user, so an admin action (MFA reset, account lock) takes effect
    immediately rather than only on the session's next natural expiry.
    Login sessions have no user_id index (this module's whole design keys
    only on the opaque token, deliberately — see `create_session`'s own
    docstring), so this SCANs the small `session:*` keyspace rather than
    maintaining a second index purely for this admin-only, infrequent
    operation. Returns the number of sessions actually revoked.
    """
    redis_client = get_redis()
    revoked = 0
    async for key in redis_client.scan_iter(match=f"{_SESSION_PREFIX}*"):
        raw = await redis_client.get(key)
        if raw is None:
            continue
        if json.loads(raw).get("user_id") == str(user_id):
            await redis_client.delete(key)
            revoked += 1
    return revoked


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


async def is_login_locked(username: str) -> bool:
    """Per-username brute-force guard on /auth/login itself (Phase 20
    hardening) — distinct from the MFA-challenge attempt cap above, which
    only kicks in *after* a password has already been guessed correctly.
    Keyed by username, not IP: an attacker behind NAT/a botnet defeats
    per-IP limits trivially, but the account being guessed at is fixed.
    """
    redis_client = get_redis()
    raw = await redis_client.get(f"{_LOGIN_FAILURE_PREFIX}{username}")
    return raw is not None and int(raw) >= _LOGIN_FAILURE_MAX_ATTEMPTS


async def record_login_failure(username: str) -> None:
    redis_client = get_redis()
    key = f"{_LOGIN_FAILURE_PREFIX}{username}"
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, _LOGIN_FAILURE_WINDOW_SECONDS)


async def clear_login_failures(username: str) -> None:
    redis_client = get_redis()
    await redis_client.delete(f"{_LOGIN_FAILURE_PREFIX}{username}")


async def get_login_lockout_status(username: str) -> dict:
    """Roadmap B1.10.5/B1.10.6 — read-only view of the same brute-force
    counter `is_login_locked`/`record_login_failure` maintain, so an admin
    can see *why* a login is currently blocked (Login Diagnostics,
    B1.10.6) instead of the lockout being an opaque black box only visible
    from inside /auth/login's own logic.
    """
    redis_client = get_redis()
    key = f"{_LOGIN_FAILURE_PREFIX}{username}"
    raw = await redis_client.get(key)
    count = int(raw) if raw is not None else 0
    ttl = await redis_client.ttl(key) if raw is not None else -2
    return {
        "locked": count >= _LOGIN_FAILURE_MAX_ATTEMPTS,
        "failure_count": count,
        "locked_seconds_remaining": ttl if ttl and ttl > 0 else None,
    }


async def force_login_lock(username: str) -> None:
    """Roadmap B1.10.5 — Account Lock, admin-triggered. Reuses the exact
    same brute-force-lockout mechanism and window (`_LOGIN_FAILURE_WINDOW_SECONDS`)
    the system already applies automatically after repeated failures,
    rather than inventing a second, incompatible "permanently locked"
    concept — from the login path's perspective, and from Login
    Diagnostics' perspective, an admin-imposed lock and an automatic one
    are the same state, just triggered differently. Unlock is the existing
    `clear_login_failures`.
    """
    redis_client = get_redis()
    key = f"{_LOGIN_FAILURE_PREFIX}{username}"
    await redis_client.set(key, _LOGIN_FAILURE_MAX_ATTEMPTS, ex=_LOGIN_FAILURE_WINDOW_SECONDS)


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
