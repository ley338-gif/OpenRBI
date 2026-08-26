import secrets

from app.core.redis import get_redis

# Roadmap B2.1 (docs/adr/0023-node-enrollment-and-trust-model.md) — same
# single-use Redis GETDEL pattern as app/core/release_tokens.py: a
# generated token exists only long enough for an operator to copy it into
# a new host's .env before that host's Session Agent presents it back.
_PREFIX = "node_enrollment_token:"
TTL_SECONDS = 60 * 60


async def create_token() -> str:
    token = secrets.token_urlsafe(32)
    redis_client = get_redis()
    await redis_client.set(f"{_PREFIX}{token}", "1", ex=TTL_SECONDS)
    return token


async def consume_token(token: str) -> bool:
    """Atomic get-and-delete so the token is single-use even under
    concurrent enrollment attempts — matches release_tokens.consume_token.
    """
    if not token:
        return False
    redis_client = get_redis()
    raw = await redis_client.getdel(f"{_PREFIX}{token}")
    return raw is not None
