import json
import secrets
import uuid

from app.core.redis import get_redis

_PREFIX = "release_token:"
_TTL_SECONDS = 5 * 60  # "zeitlich begrenzt" (project brief §20)


async def create_token(quarantine_file_id: uuid.UUID, user_id: uuid.UUID) -> str:
    token = secrets.token_urlsafe(32)
    redis_client = get_redis()
    await redis_client.set(
        f"{_PREFIX}{token}",
        json.dumps({"quarantine_file_id": str(quarantine_file_id), "user_id": str(user_id)}),
        ex=_TTL_SECONDS,
    )
    return token


async def consume_token(token: str) -> dict | None:
    """Atomic get-and-delete (Redis GETDEL) so the token is single-use even
    under concurrent requests (project brief §20: "darf nicht mehrfach
    verwendet werden") — there is no window where two requests could both
    read the token before either deletes it.
    """
    redis_client = get_redis()
    raw = await redis_client.getdel(f"{_PREFIX}{token}")
    if raw is None:
        return None
    return json.loads(raw)
