"""An isolated session is preserved for investigation (docs/session-lifecycle.md):
its owner can't end it, only an administrator can (Kill), and it doesn't count
against the owner's session limit, so they can keep browsing in a new session.
"""

import pytest

from app.models.browser_session import BrowserSession
from app.models.enums import SessionStatus
from app.services.sessions import count_active_sessions_for_user
from tests.conftest import login, make_user


async def _session(db, user, status: SessionStatus) -> BrowserSession:
    session = BrowserSession(user_id=user.id, status=status)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [SessionStatus.ISOLATED, SessionStatus.ISOLATING])
async def test_owner_cannot_end_an_isolated_session(db, client, status):
    user, password = await make_user(db, role_name="USER")
    session = await _session(db, user, status)
    cookie = await login(client, user.username, password)

    response = await client.post(f"/sessions/{session.id}/terminate", cookies={"openrbi_session": cookie})

    assert response.status_code == 409, response.text
    assert "administrator" in response.json()["detail"]
    await db.refresh(session)
    assert session.status == status


@pytest.mark.asyncio
async def test_isolated_session_does_not_count_against_the_session_limit(db):
    user, _ = await make_user(db, role_name="USER")
    await _session(db, user, SessionStatus.ISOLATED)
    await _session(db, user, SessionStatus.ISOLATING)
    assert await count_active_sessions_for_user(db, user.id) == 0

    await _session(db, user, SessionStatus.DISCONNECTED)
    assert await count_active_sessions_for_user(db, user.id) == 1
