"""Roadmap Phase B / B1.10.6 — Login Diagnostics (GET /admin/login-diagnostics),
against the real, already-running backend (never mocked). Strictly
read-only: no password is ever tested, no auth is ever performed on the
user's behalf.
"""

import pytest

from tests.conftest import login_with_mfa_enrollment, make_user


@pytest.mark.asyncio
async def test_diagnostics_for_unknown_username(db, client):
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)

    r = await client.get(
        "/admin/login-diagnostics", params={"username": "no_such_user_xyz"}, cookies={"openrbi_session": admin_cookie}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["account_exists"] is False
    assert body["is_active"] is None
    assert body["mfa_enabled"] is None
    assert any("no account found" in reason.lower() for reason in body["possible_reasons"])


@pytest.mark.asyncio
async def test_diagnostics_for_disabled_account(db, client):
    from app.services.users import set_active

    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)
    target, _ = await make_user(db, role_name="USER")
    await set_active(db, target, active=False, actor_id=admin.id)
    await db.commit()

    r = await client.get(
        "/admin/login-diagnostics", params={"username": target.username}, cookies={"openrbi_session": admin_cookie}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["account_exists"] is True
    assert body["is_active"] is False
    assert any("disabled" in reason.lower() for reason in body["possible_reasons"])


@pytest.mark.asyncio
async def test_diagnostics_for_locked_account(db, client):
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)
    target, _ = await make_user(db, role_name="USER")

    r = await client.post(f"/admin/users/{target.id}/lock", cookies={"openrbi_session": admin_cookie})
    assert r.status_code == 200

    r = await client.get(
        "/admin/login-diagnostics", params={"username": target.username}, cookies={"openrbi_session": admin_cookie}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lockout"]["locked"] is True
    assert any("locked out" in reason.lower() for reason in body["possible_reasons"])

    await client.post(f"/admin/users/{target.id}/unlock", cookies={"openrbi_session": admin_cookie})


@pytest.mark.asyncio
async def test_diagnostics_for_healthy_account_has_no_blocker_reasons(db, client):
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)
    target, _ = await make_user(db, role_name="USER")

    r = await client.get(
        "/admin/login-diagnostics", params={"username": target.username}, cookies={"openrbi_session": admin_cookie}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["account_exists"] is True
    assert body["is_active"] is True
    assert body["lockout"]["locked"] is False
    # No password test ever happens — this endpoint has no concept of
    # "verified this password", only structural signals.
    assert "password" not in str(body).lower() or "cannot be verified" in " ".join(body["possible_reasons"]).lower()


@pytest.mark.asyncio
async def test_diagnostics_for_admin_role_without_mfa_enrolled(db, client):
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)
    target_admin, _ = await make_user(db, role_name="ADMIN")  # not enrolled via login_with_mfa_enrollment

    r = await client.get(
        "/admin/login-diagnostics",
        params={"username": target_admin.username},
        cookies={"openrbi_session": admin_cookie},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mfa_enabled"] is False
    assert any("requires mfa" in reason.lower() for reason in body["possible_reasons"])


@pytest.mark.asyncio
async def test_diagnostics_allows_security_reviewer_but_not_a_plain_user(db, client):
    reviewer, reviewer_password = await make_user(db, role_name="SECURITY_REVIEWER")
    reviewer_cookie = await login_with_mfa_enrollment(client, reviewer.username, reviewer_password)
    user, user_password = await make_user(db, role_name="USER")

    r = await client.get(
        "/admin/login-diagnostics", params={"username": user.username}, cookies={"openrbi_session": reviewer_cookie}
    )
    assert r.status_code == 200, r.text

    login_r = await client.post("/auth/login", json={"username": user.username, "password": user_password})
    user_cookie = login_r.cookies.get("openrbi_session")
    r = await client.get(
        "/admin/login-diagnostics", params={"username": user.username}, cookies={"openrbi_session": user_cookie}
    )
    assert r.status_code == 403
