"""Roadmap Phase B / B1.10.5 — Account Lock/Unlock and MFA-reset session
revocation, against the real, already-running backend (never mocked).
"""

import pytest
from sqlalchemy import select

from app.models.security_event import SecurityEvent
from tests.conftest import login_with_mfa_enrollment, make_user


@pytest.mark.asyncio
async def test_lock_blocks_login_and_unlock_restores_it(db, client):
    user, password = await make_user(db, role_name="USER")
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)

    r = await client.get(f"/admin/users/{user.id}/lockout", cookies={"openrbi_session": admin_cookie})
    assert r.status_code == 200, r.text
    assert r.json()["locked"] is False

    r = await client.post(f"/admin/users/{user.id}/lock", cookies={"openrbi_session": admin_cookie})
    assert r.status_code == 200, r.text
    assert r.json()["locked"] is True

    # A correct-password login is now rejected the same way the automatic
    # brute-force lockout rejects one — same 429, not a different/leakier
    # error that would reveal the password was actually right.
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    assert r.status_code == 429

    result = await db.execute(
        select(SecurityEvent).where(SecurityEvent.user_id == user.id, SecurityEvent.event_type == "ACCOUNT_LOCKED")
    )
    assert result.scalars().first() is not None

    r = await client.post(f"/admin/users/{user.id}/unlock", cookies={"openrbi_session": admin_cookie})
    assert r.status_code == 200, r.text
    assert r.json()["locked"] is False

    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    assert r.status_code == 200

    result = await db.execute(
        select(SecurityEvent).where(SecurityEvent.user_id == user.id, SecurityEvent.event_type == "ACCOUNT_UNLOCKED")
    )
    assert result.scalars().first() is not None


@pytest.mark.asyncio
async def test_lock_revokes_the_users_active_session(db, client):
    user, password = await make_user(db, role_name="USER")
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)

    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    user_cookie = r.cookies.get("openrbi_session")
    r = await client.get("/auth/me", cookies={"openrbi_session": user_cookie})
    assert r.status_code == 200

    await client.post(f"/admin/users/{user.id}/lock", cookies={"openrbi_session": admin_cookie})

    r = await client.get("/auth/me", cookies={"openrbi_session": user_cookie})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_lockout_endpoints_are_admin_only(db, client):
    target, _ = await make_user(db, role_name="USER")
    reviewer, reviewer_password = await make_user(db, role_name="SECURITY_REVIEWER")
    reviewer_cookie = await login_with_mfa_enrollment(client, reviewer.username, reviewer_password)

    r = await client.get(f"/admin/users/{target.id}/lockout", cookies={"openrbi_session": reviewer_cookie})
    assert r.status_code == 403
    r = await client.post(f"/admin/users/{target.id}/lock", cookies={"openrbi_session": reviewer_cookie})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_mfa_reset_revokes_the_users_active_session(db, client):
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)
    target_admin, target_password = await make_user(db, role_name="ADMIN")
    target_cookie = await login_with_mfa_enrollment(client, target_admin.username, target_password)

    r = await client.get("/auth/me", cookies={"openrbi_session": target_cookie})
    assert r.status_code == 200

    r = await client.post(f"/mfa/admin/users/{target_admin.id}/reset", cookies={"openrbi_session": admin_cookie})
    assert r.status_code == 200, r.text

    r = await client.get("/auth/me", cookies={"openrbi_session": target_cookie})
    assert r.status_code == 401

    result = await db.execute(
        select(SecurityEvent).where(SecurityEvent.user_id == target_admin.id, SecurityEvent.event_type == "MFA_RESET")
    )
    event = result.scalars().first()
    assert event is not None
    assert event.metadata_json["sessions_revoked"] >= 1
