from datetime import UTC, datetime

import pytest

from app.models.browser_session import BrowserSession
from app.models.enums import SessionStatus
from tests.conftest import login_with_mfa_enrollment, make_user


@pytest.mark.asyncio
async def test_session_overview_is_admin_data(db, client):
    user, password = await make_user(db, username="sessions-normal", role_name="USER")
    login = await client.post("/auth/login", json={"username": user.username, "password": password})
    response = await client.get(
        "/admin/sessions", cookies={"openrbi_session": login.cookies.get("openrbi_session")}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_session_overview_search_filter_pagination_and_stats(db, client):
    admin, password = await make_user(db, username="sessions-admin", role_name="ADMIN")
    owner, _ = await make_user(db, username="session-distinct-owner", role_name="USER")
    session = BrowserSession(
        user_id=owner.id,
        status=SessionStatus.DISCONNECTED,
        started_at=datetime.now(UTC),
        last_activity_at=datetime.now(UTC),
    )
    db.add(session)
    await db.commit()
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    response = await client.get(
        "/admin/sessions?search=distinct&session_status=DISCONNECTED&limit=1&offset=0",
        cookies={"openrbi_session": cookie},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(session.id)
    assert body["items"][0]["username"] == owner.username
    assert body["items"][0]["status"] == "DISCONNECTED"
    assert body["stats"]["active"] >= 1
    assert body["stats"]["sessions_today"] >= 1
    assert "DISCONNECTED" in body["statuses"]


@pytest.mark.asyncio
async def test_session_detail_idor_is_rejected_for_normal_user(db, client):
    owner, owner_password = await make_user(db, username="session-idor-owner", role_name="USER")
    other, _ = await make_user(db, username="session-idor-other", role_name="USER")
    session = BrowserSession(user_id=other.id, status=SessionStatus.TERMINATED)
    db.add(session)
    await db.commit()
    login = await client.post(
        "/auth/login", json={"username": owner.username, "password": owner_password}
    )
    response = await client.get(
        f"/admin/sessions/{session.id}",
        cookies={"openrbi_session": login.cookies.get("openrbi_session")},
    )
    assert response.status_code == 403
