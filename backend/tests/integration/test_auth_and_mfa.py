"""Auth/MFA checklist items from docs/development.md's Phase 21 list:
disabled user cannot start a session (nor even log in), admin login
requires MFA, recovery codes are single-use, MFA reset generates an audit
event, and login failures/lockout are auditable.
"""
import uuid

import pyotp
import pytest
from sqlalchemy import select, text

from fastapi import Response

from app.config import Settings
from app.core.redis import get_redis
from app.core.session_cookies import set_session_cookie
from app.core.sessions import clear_login_failures
from app.models.enums import SecurityEventType
from app.models.mfa import RecoveryCode
from app.models.security_event import SecurityEvent
from app.services.mfa import reset_mfa
from app.services.users import set_active

from tests.conftest import login_with_mfa_enrollment, make_user


@pytest.mark.asyncio
async def test_disabled_user_cannot_login(db, client):
    user, password = await make_user(db, role_name="USER")
    await set_active(db, user, active=False, actor_id=uuid.uuid4())
    await db.commit()

    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    assert r.status_code == 401
    # Fails closed *identically* to a wrong password — never a distinct
    # "account disabled" message that would let an attacker distinguish a
    # disabled account from a nonexistent one.
    assert r.json()["detail"] == "invalid credentials"


@pytest.mark.asyncio
async def test_wrong_password_and_unknown_user_get_identical_response(client):
    r1 = await client.post("/auth/login", json={"username": f"pytest_nonexistent_{uuid.uuid4().hex}", "password": "x"})
    r2 = await client.post("/auth/login", json={"username": "thomas", "password": "definitely-wrong"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()


@pytest.mark.asyncio
async def test_admin_login_requires_mfa_enrollment(db, client):
    user, password = await make_user(db, role_name="ADMIN")
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "mfa_enrollment_required"
    # No session cookie may be issued on this branch — password-only is
    # never enough for a mandatory-MFA role.
    assert "openrbi_session" not in r.cookies


@pytest.mark.asyncio
async def test_admin_full_mfa_enrollment_grants_real_session(db, client):
    user, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, user.username, password)

    r = await client.get("/auth/me", cookies={"openrbi_session": cookie})
    assert r.status_code == 200
    assert r.json()["username"] == user.username
    assert r.json()["role"] == "ADMIN"


@pytest.mark.asyncio
async def test_production_session_cookie_has_required_security_attributes():
    response = Response()
    config = Settings.model_construct(
        environment="production",
        session_cookie_name="openrbi_session",
        session_ttl_seconds=28800,
    )
    set_session_cookie(response, "opaque-test-token", config)

    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie
    assert "max-age=28800" in set_cookie


@pytest.mark.asyncio
async def test_expired_server_side_session_is_rejected(db, client):
    user, password = await make_user(db, role_name="USER")
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    cookie = r.cookies["openrbi_session"]
    await get_redis().expire(f"session:{cookie}", 0)

    r = await client.get("/auth/me", cookies={"openrbi_session": cookie})
    assert r.status_code == 401
    assert r.json()["detail"] == "session expired or invalid"


@pytest.mark.asyncio
async def test_security_reviewer_also_requires_mandatory_mfa(db, client):
    user, password = await make_user(db, role_name="SECURITY_REVIEWER")
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    assert r.json()["status"] == "mfa_enrollment_required"


@pytest.mark.asyncio
async def test_recovery_code_is_single_use(db, client):
    user, password = await make_user(db, role_name="ADMIN")
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    mfa_token = r.json()["mfa_token"]
    r = await client.post("/mfa/setup/enroll", json={"mfa_token": mfa_token})
    uri = r.json()["otpauth_uri"]
    secret = dict(part.split("=") for part in uri.split("?", 1)[1].split("&"))["secret"]
    code = pyotp.TOTP(secret).now()
    r = await client.post("/mfa/setup/confirm", json={"mfa_token": mfa_token, "code": code})
    recovery_code = r.json()["recovery_codes"][0]

    # Fresh login, this time use the recovery code instead of a live TOTP code.
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    mfa_token = r.json()["mfa_token"]
    r = await client.post("/auth/mfa/verify", json={"mfa_token": mfa_token, "code": recovery_code})
    assert r.status_code == 200, r.text

    # Reusing the same recovery code must fail — it's already consumed.
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    mfa_token = r.json()["mfa_token"]
    r = await client.post("/auth/mfa/verify", json={"mfa_token": mfa_token, "code": recovery_code})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_mfa_reset_generates_audit_event_and_disables_mfa(db, client):
    user, password = await make_user(db, role_name="ADMIN")
    await login_with_mfa_enrollment(client, user.username, password)

    admin_actor_id = uuid.uuid4()
    await db.refresh(user)
    await reset_mfa(db, user, admin_actor_id)
    await db.commit()

    await db.refresh(user)
    assert user.mfa_enabled is False
    assert user.totp_secret_encrypted is None

    result = await db.execute(
        select(RecoveryCode).where(RecoveryCode.user_id == user.id)
    )
    assert result.scalars().first() is None  # recovery codes wiped on reset

    result = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.user_id == user.id, SecurityEvent.event_type == SecurityEventType.MFA_RESET
        )
    )
    assert result.scalars().first() is not None


@pytest.mark.asyncio
async def test_admin_mfa_reset_endpoint_still_works_after_router_split(db, client):
    """app/api/admin_mfa.py was split out of app/api/mfa.py (Productization
    v0.1.1, docs/adr/0011-user-admin-listener-separation.md) — same path
    (/mfa/admin/users/{id}/reset), same business logic, moved module.
    Regression test that the split didn't silently change behavior.
    """
    admin, admin_password = await make_user(db, role_name="ADMIN")
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)

    target, target_password = await make_user(db, role_name="ADMIN")
    await login_with_mfa_enrollment(client, target.username, target_password)
    await db.refresh(target)
    assert target.mfa_enabled is True

    r = await client.post(f"/mfa/admin/users/{target.id}/reset", cookies={"openrbi_session": admin_cookie})
    assert r.status_code == 200, r.text

    await db.refresh(target)
    assert target.mfa_enabled is False


@pytest.mark.asyncio
async def test_admin_mfa_reset_endpoint_is_still_admin_only(db, client):
    reviewer, reviewer_password = await make_user(db, role_name="SECURITY_REVIEWER")
    reviewer_cookie = await login_with_mfa_enrollment(client, reviewer.username, reviewer_password)

    target, _ = await make_user(db, role_name="USER")

    r = await client.post(f"/mfa/admin/users/{target.id}/reset", cookies={"openrbi_session": reviewer_cookie})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_login_lockout_after_repeated_failures(db, client):
    user, password = await make_user(db, role_name="USER")
    await clear_login_failures(user.username)

    for _ in range(10):
        r = await client.post("/auth/login", json={"username": user.username, "password": "wrong"})
        assert r.status_code == 401

    # Even the *correct* password is now rejected — this is an account
    # lockout, not just a per-attempt check.
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    assert r.status_code == 429

    result = await db.execute(
        text("SELECT 1 FROM security_events WHERE event_type = 'LOGIN_LOCKED' "
             "AND metadata_json->>'username' = :username"),
        {"username": user.username},
    )
    assert result.first() is not None

    await clear_login_failures(user.username)
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    assert r.status_code == 200
