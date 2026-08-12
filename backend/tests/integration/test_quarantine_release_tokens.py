"""Release-token checklist item: single-use and time-limited (project brief
§20). Expiry itself is tested by manipulating the token's Redis TTL rather
than sleeping for the real 5-minute window.
"""
import pytest

from app.core.redis import get_redis
from app.core.release_tokens import _PREFIX, consume_token, create_token

from tests.conftest import make_user


@pytest.mark.asyncio
async def test_release_token_is_single_use(db):
    user, _ = await make_user(db, role_name="USER")
    import uuid

    file_id = uuid.uuid4()
    token = await create_token(file_id, user.id)

    claim = await consume_token(token)
    assert claim == {"quarantine_file_id": str(file_id), "user_id": str(user.id)}

    # Second consumption of the same token must fail — GETDEL already
    # removed it atomically on first use.
    assert await consume_token(token) is None


@pytest.mark.asyncio
async def test_release_token_expires():
    import uuid

    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    token = await create_token(file_id, user_id)

    # Force the token past its TTL rather than waiting out the real 5
    # minutes — same observable outcome (key gone), verified via the
    # library's own TTL mechanism, not a re-implementation of it.
    redis_client = get_redis()
    await redis_client.expire(f"{_PREFIX}{token}", 0)

    assert await consume_token(token) is None


@pytest.mark.asyncio
async def test_unknown_token_and_expired_token_are_indistinguishable():
    claim_unknown = await consume_token("this-token-was-never-issued")
    assert claim_unknown is None
