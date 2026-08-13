"""Roadmap Phase B / B1.9 — first-run bootstrap API (app/api/setup.py),
against the real, already-running backend (see tests/conftest.py's module
docstring for why every integration test in this project runs this way,
not mocked).

system_state is a singleton row (app/models/system_state.py, same pattern
as ldap_config.py's LDAP_CONFIG_ID), not per-test-prefixed data — every
test in this file resets it before and after via _reset_system_state, the
same isolation approach test_admin_ldap.py's _reset_ldap_config uses for
its own singleton row.

The plaintext setup token only ever exists at generation time (only its
Argon2 hash is persisted) and is normally printed to the backend
process's own stdout at startup — tests mint their own via
regenerate_setup_token() directly (the same function app/main.py's
startup hook calls), exactly the intended way to obtain one outside of
reading a log.
"""

import pyotp
import pytest
import pytest_asyncio
from sqlalchemy import delete, text

from app.models.system_state import SYSTEM_STATE_ID, SystemState
from app.models.user import User
from app.services.setup_service import regenerate_setup_token
from app.core.sessions import clear_login_failures
from tests.conftest import login_with_mfa_enrollment, make_user, unique_username


@pytest_asyncio.fixture(autouse=True)
async def _reset_system_state(db):
    """Resets only the system_state singleton row and the setup rate-limit
    key — never bulk-deletes users by the shared `pytest_` prefix, since
    other test files running in the same session own their own
    prefix-matching users with live FK references (security_events,
    sessions, ...) that aren't cleaned up until the whole session's
    _cleanup_test_data fixture runs at the end (tests/conftest.py). Any
    user this file's own tests create is swept up by that same
    session-scoped fixture like every other file's — system_state's
    setup_admin_user_id -> users FK is ON DELETE SET NULL, so that cleanup
    never needs this fixture's help.
    """

    async def _reset():
        await db.execute(delete(SystemState).where(SystemState.id == SYSTEM_STATE_ID))
        await db.commit()
        # The setup-token rate limiter (app/services/setup_service.py) is
        # keyed by a single fixed pseudo-username shared across every test
        # in this file — must be reset independently or one test's failed
        # attempts leak into the next.
        await clear_login_failures("__setup_bootstrap__")

    await _reset()
    yield
    await _reset()


async def _fresh_token(db) -> str:
    token = await regenerate_setup_token(db)
    assert token
    return token


def _bootstrap_username() -> str:
    return unique_username()


@pytest.mark.asyncio
async def test_fresh_install_reports_setup_required(db, client):
    r = await client.get("/setup/status")
    assert r.status_code == 200
    assert r.json() == {"setup_required": True}


@pytest.mark.asyncio
async def test_status_never_leaks_anything_beyond_the_flag(db, client):
    r = await client.get("/setup/status")
    assert set(r.json().keys()) == {"setup_required"}


@pytest.mark.asyncio
async def test_full_bootstrap_flow_creates_admin_with_mfa_and_closes_setup(db, client):
    token = await _fresh_token(db)
    username = _bootstrap_username()

    r = await client.post(
        "/setup/admin", json={"setup_token": token, "username": username, "password": "Bootstrap-Pw2026!"}
    )
    assert r.status_code == 200, r.text
    mfa_token = r.json()["mfa_token"]

    # Password went through the existing Argon2 hashing (app/core/security.py),
    # not a bootstrap-specific scheme: a real local login with the correct
    # password succeeds and, since MFA isn't enrolled yet, hits the exact
    # same mandatory-enrollment branch any other freshly-created ADMIN would
    # (app/api/auth.py's _MFA_MANDATORY_ROLES check).
    r = await client.post("/auth/login", json={"username": username, "password": "Bootstrap-Pw2026!"})
    assert r.status_code == 200
    assert r.json()["status"] == "mfa_enrollment_required"

    r = await client.post("/mfa/setup/enroll", json={"mfa_token": mfa_token})
    assert r.status_code == 200, r.text
    secret = dict(part.split("=") for part in r.json()["otpauth_uri"].split("?", 1)[1].split("&"))["secret"]

    # Setup is not yet complete until this call succeeds.
    r = await client.get("/setup/status")
    assert r.json()["setup_required"] is True

    r = await client.post("/setup/mfa/confirm", json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert len(body["recovery_codes"]) > 0
    assert r.cookies.get("openrbi_session")

    r = await client.get("/setup/status")
    assert r.json()["setup_required"] is False

    result = await db.execute(
        text("SELECT r.name FROM users u JOIN roles r ON r.id = u.role_id WHERE u.username = :u"), {"u": username}
    )
    assert result.scalar_one() == "ADMIN"

    result = await db.execute(text("SELECT mfa_enabled FROM users WHERE username = :u"), {"u": username})
    assert result.scalar_one() is True

    result = await db.execute(
        text("SELECT event_type::text FROM security_events se JOIN users u ON u.id = se.user_id "
             "WHERE u.username = :u ORDER BY se.created_at"),
        {"u": username},
    )
    events = [row[0] for row in result.all()]
    assert "INITIAL_ADMIN_CREATED" in events
    assert "MFA_ENROLLED" in events
    assert "SYSTEM_INITIALIZED" in events


@pytest.mark.asyncio
async def test_setup_endpoints_stop_working_after_initialization(db, client):
    token = await _fresh_token(db)
    username = _bootstrap_username()
    r = await client.post(
        "/setup/admin", json={"setup_token": token, "username": username, "password": "Bootstrap-Pw2026!"}
    )
    mfa_token = r.json()["mfa_token"]
    r = await client.post("/mfa/setup/enroll", json={"mfa_token": mfa_token})
    secret = dict(part.split("=") for part in r.json()["otpauth_uri"].split("?", 1)[1].split("&"))["secret"]
    r = await client.post("/setup/mfa/confirm", json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200

    r = await client.get("/setup/status")
    assert r.json()["setup_required"] is False

    r = await client.post(
        "/setup/admin", json={"setup_token": "irrelevant", "username": "someone_else", "password": "whatever"}
    )
    assert r.status_code == 409

    r = await client.post("/setup/mfa/confirm", json={"mfa_token": "irrelevant", "code": "000000"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_second_bootstrap_admin_cannot_be_created(db, client):
    token = await _fresh_token(db)
    username_a = _bootstrap_username()
    r = await client.post(
        "/setup/admin", json={"setup_token": token, "username": username_a, "password": "Bootstrap-Pw2026!"}
    )
    assert r.status_code == 200

    # Same still-valid token, second admin creation attempt — must not
    # create a second user while the first bootstrap is still in progress
    # (uncompleted MFA); this exercises the retry-reuses-the-same-account
    # path, not a second admin.
    username_b = _bootstrap_username()
    r = await client.post(
        "/setup/admin", json={"setup_token": token, "username": username_b, "password": "Bootstrap-Pw2026!"}
    )
    assert r.status_code == 200, r.text

    result = await db.execute(text("SELECT COUNT(*) FROM users WHERE username IN (:a, :b)"), {"a": username_a, "b": username_b})
    # username_a no longer exists (renamed to username_b by the retry path);
    # exactly one bootstrap-candidate row exists at any time.
    assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_wrong_setup_token_is_rejected(db, client):
    await _fresh_token(db)  # ensures a real token exists and is NOT the one used below
    r = await client.post(
        "/setup/admin",
        json={"setup_token": "definitely-the-wrong-token", "username": _bootstrap_username(), "password": "x"},
    )
    assert r.status_code == 400
    assert "Traceback" not in r.text


@pytest.mark.asyncio
async def test_username_collision_with_an_unrelated_existing_user_is_rejected_cleanly(db, client):
    """Real bug, found manually against a live dev stack, not hypothetical:
    when no bootstrap is in progress yet (system_state.setup_admin_user_id
    is None) and the requested username already belongs to a completely
    unrelated local account, create_user() raises UserServiceError — which
    originally propagated out of create_bootstrap_admin as an unhandled
    exception (a raw 500), not the same clean 400 every other bootstrap
    failure returns.
    """
    existing_user, _ = await make_user(db, role_name="USER")
    token = await _fresh_token(db)
    r = await client.post(
        "/setup/admin",
        json={"setup_token": token, "username": existing_user.username, "password": "Bootstrap-Pw2026!"},
    )
    assert r.status_code == 400, r.text
    assert "Traceback" not in r.text
    assert "Internal Server Error" not in r.text


@pytest.mark.asyncio
async def test_repeated_wrong_setup_tokens_are_rate_limited(db, client):
    await _fresh_token(db)
    username = _bootstrap_username()
    for _ in range(10):
        r = await client.post(
            "/setup/admin", json={"setup_token": "wrong", "username": username, "password": "x"}
        )
        assert r.status_code == 400

    r = await client.post(
        "/setup/admin", json={"setup_token": "wrong", "username": username, "password": "x"}
    )
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_deleting_all_users_does_not_reopen_setup(db, client):
    token = await _fresh_token(db)
    username = _bootstrap_username()
    r = await client.post(
        "/setup/admin", json={"setup_token": token, "username": username, "password": "Bootstrap-Pw2026!"}
    )
    mfa_token = r.json()["mfa_token"]
    r = await client.post("/mfa/setup/enroll", json={"mfa_token": mfa_token})
    secret = dict(part.split("=") for part in r.json()["otpauth_uri"].split("?", 1)[1].split("&"))["secret"]
    r = await client.post("/setup/mfa/confirm", json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200

    # The privilege-escalation scenario Section 8 explicitly calls out:
    # every user gone must NOT reopen the public bootstrap endpoint.
    await db.execute(text("DELETE FROM security_events"))
    await db.execute(text("DELETE FROM recovery_codes"))
    await db.execute(delete(User).where(User.username == username))
    await db.commit()

    r = await client.get("/setup/status")
    assert r.json()["setup_required"] is False

    r = await client.post(
        "/setup/admin", json={"setup_token": "anything", "username": "new_admin", "password": "x"}
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_secrets_never_appear_in_setup_responses_or_audit(db, client):
    token = await _fresh_token(db)
    username = _bootstrap_username()
    password = "Very-Secret-Bootstrap-Pw2026!"

    r = await client.post("/setup/admin", json={"setup_token": token, "username": username, "password": password})
    assert password not in r.text
    assert token not in r.text
    mfa_token = r.json()["mfa_token"]

    r = await client.post("/mfa/setup/enroll", json={"mfa_token": mfa_token})
    secret = dict(part.split("=") for part in r.json()["otpauth_uri"].split("?", 1)[1].split("&"))["secret"]
    r = await client.post("/setup/mfa/confirm", json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()})
    assert password not in r.text
    assert token not in r.text
    assert secret not in r.text

    result = await db.execute(
        text("SELECT metadata_json FROM security_events se JOIN users u ON u.id = se.user_id "
             "WHERE u.username = :u"),
        {"u": username},
    )
    for (metadata,) in result.all():
        blob = str(metadata)
        assert password not in blob
        assert token not in blob
        assert secret not in blob


@pytest.mark.asyncio
async def test_local_login_and_mfa_unaffected_by_setup_module(db, client):
    # Regression: a normal, unrelated local account's login/MFA behavior
    # must be completely untouched by anything in this file.
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    assert cookie
