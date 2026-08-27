"""Roadmap Phase B / B1.10.4 — bulk session revocation from the User Detail
page (POST /admin/users/{id}/sessions/revoke), against the real,
already-running backend + Session Agent (never mocked).
"""

import pytest
from sqlalchemy import select

from app.models.security_event import SecurityEvent
from tests.conftest import create_session_tolerating_transient_capacity, login_with_mfa_enrollment, make_user


@pytest.mark.asyncio
async def test_revoke_terminates_every_live_session_and_is_audited(db, client):
    # max_sessions_per_user is 1 by default, so a real user can only ever
    # have one live session at a time — this still exercises the full
    # bulk-revoke path (lookup, terminate, audit, response shape), just
    # with a batch size of one rather than fabricating a quota bypass.
    owner, _ = await make_user(db, role_name="USER")
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)

    session_a = await create_session_tolerating_transient_capacity(db, owner)
    await db.commit()

    r = await client.post(f"/admin/users/{owner.id}/sessions/revoke", cookies={"openrbi_session": admin_cookie})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["terminated_count"] == 1
    assert body["session_ids"] == [str(session_a.id)]

    r = await client.get(f"/admin/sessions/{session_a.id}", cookies={"openrbi_session": admin_cookie})
    assert r.json()["status"] == "TERMINATED"

    result = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.user_id == owner.id, SecurityEvent.event_type == "USER_SESSIONS_REVOKED"
        )
    )
    event = result.scalars().first()
    assert event is not None
    assert event.metadata_json["session_count"] == 1

    # The individual session still gets its own SESSION_TERMINATED event —
    # the bulk event is additional, not a replacement.
    result = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.session_id == session_a.id, SecurityEvent.event_type == "SESSION_TERMINATED"
        )
    )
    assert result.scalars().first() is not None


@pytest.mark.asyncio
async def test_revoke_with_no_live_sessions_is_a_clean_no_op(db, client):
    owner, _ = await make_user(db, role_name="USER")
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)

    r = await client.post(f"/admin/users/{owner.id}/sessions/revoke", cookies={"openrbi_session": admin_cookie})
    assert r.status_code == 200, r.text
    assert r.json() == {"terminated_count": 0, "session_ids": []}

    # No fabricated audit event for a no-op action.
    result = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.user_id == owner.id, SecurityEvent.event_type == "USER_SESSIONS_REVOKED"
        )
    )
    assert result.scalars().first() is None


@pytest.mark.asyncio
async def test_revoke_is_admin_only(db, client):
    owner, _ = await make_user(db, role_name="USER")
    reviewer, reviewer_password = await make_user(db, role_name="SECURITY_REVIEWER")
    reviewer_cookie = await login_with_mfa_enrollment(client, reviewer.username, reviewer_password)

    r = await client.post(f"/admin/users/{owner.id}/sessions/revoke", cookies={"openrbi_session": reviewer_cookie})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_revoke_returns_404_for_unknown_user(db, client):
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)
    import uuid

    r = await client.post(f"/admin/users/{uuid.uuid4()}/sessions/revoke", cookies={"openrbi_session": admin_cookie})
    assert r.status_code == 404
