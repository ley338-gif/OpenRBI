"""Security follow-ups from the 2026-10 documentation review.

- A role change revokes the user's login sessions, so a USER without MFA who
  is promoted can't keep using the admin API with the session they had.
- Calls to the default node that pass no explicit connection use the token
  the listener mode resolves to (a scoped one on a Segmented listener,
  docs/adr/0025), like every node-specific call.
"""

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core import session_agent_client
from app.models.enums import SecurityEventType
from app.models.security_event import SecurityEvent
from app.services import nodes
from tests.conftest import login, login_with_mfa_enrollment, make_user


@pytest.mark.asyncio
async def test_promotion_revokes_the_existing_session(db, client):
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)
    user, user_password = await make_user(db, role_name="USER")
    user_cookie = await login(client, user.username, user_password)
    assert (await client.get("/auth/me", cookies={"openrbi_session": user_cookie})).status_code == 200

    response = await client.put(
        f"/admin/users/{user.id}/role",
        json={"role": "ADMIN"},
        cookies={"openrbi_session": admin_cookie},
    )
    assert response.status_code == 200, response.text

    # The old, MFA-less session is gone: no admin access without logging in again.
    assert (await client.get("/auth/me", cookies={"openrbi_session": user_cookie})).status_code == 401
    assert (await client.get("/admin/users", cookies={"openrbi_session": user_cookie})).status_code == 401
    # Logging in again goes through mandatory MFA enrollment for the new role.
    login_response = await client.post("/auth/login", json={"username": user.username, "password": user_password})
    assert login_response.json()["status"] == "mfa_enrollment_required"

    metadata = await db.scalar(
        select(SecurityEvent.metadata_json).where(
            SecurityEvent.user_id == user.id, SecurityEvent.event_type == SecurityEventType.USER_ROLE_CHANGED
        )
    )
    assert metadata["sessions_revoked"] == 1


@pytest.mark.asyncio
async def test_unchanged_role_keeps_the_session(db, client):
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)
    user, user_password = await make_user(db, role_name="USER")
    user_cookie = await login(client, user.username, user_password)

    response = await client.put(
        f"/admin/users/{user.id}/role",
        json={"role": "USER"},
        cookies={"openrbi_session": admin_cookie},
    )
    assert response.status_code == 200, response.text
    assert (await client.get("/auth/me", cookies={"openrbi_session": user_cookie})).status_code == 200


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("user", "scoped-user-token"), ("admin", "scoped-admin-token"), ("both", "shared-token")],
)
@pytest.mark.asyncio
async def test_default_node_calls_use_the_listener_token(monkeypatch, mode, expected):
    settings = get_settings().model_copy(
        update={
            "listener_mode": mode,
            "session_agent_api_token": "shared-token",
            "session_agent_api_token_user": "scoped-user-token",
            "session_agent_api_token_admin": "scoped-admin-token",
        }
    )
    monkeypatch.setattr(nodes, "get_settings", lambda: settings)

    async with session_agent_client._client() as client:
        assert client.headers["X-Openrbi-Agent-Token"] == expected
        assert str(client.base_url).rstrip("/") == settings.session_agent_base_url.rstrip("/")
