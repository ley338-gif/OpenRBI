"""Integration test fixtures.

These tests run against the real, live stack (real Postgres, real Redis,
real Session Agent talking to the real Docker socket) — not mocks — matching
how every phase of this project has actually been verified so far. They are
meant to be run with `docker compose exec backend pytest` (see
scripts/run-integration-tests.sh), never against a throwaway/unit-test-only
database, because several of them (session lifecycle, quarantine) need the
Session Agent and Postgres exactly as deployed.

All test-created rows are named with the PREFIX below and swept up by the
session-scoped `_cleanup_test_data` fixture — never assume per-test rollback,
since tests commit (like real request handlers do) so that a later test step
issued through a fresh DB session or a real HTTP request can see the data.
"""

import uuid

import httpx
import pyotp
import pytest_asyncio
from sqlalchemy import text

from app.core.security import hash_password
from app.db.session import async_session_factory
from app.services.users import create_user

PREFIX = "pytest_"
BASE_URL = "http://localhost:8000"


def unique_username() -> str:
    return f"{PREFIX}{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def db():
    async with async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as c:
        yield c


async def make_user(db, *, role_name: str = "USER", password: str = "Test-Password!2026"):
    """Creates a real, committed user via the same service function the
    admin API uses — not a hand-rolled INSERT — so tests exercise the real
    validation path. Returns (User, plaintext_password).
    """
    username = unique_username()
    user = await create_user(
        db,
        username=username,
        password=password,
        role_name=role_name,
        group_ids=[],
        created_by=uuid.uuid4(),
    )
    await db.commit()
    return user, password


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    """Plain login for a USER-role account (no MFA). Returns the session
    cookie value.
    """
    r = await client.post("/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    body = r.json()
    assert body["status"] == "ok", f"expected immediate login, got {body}"
    cookie = r.cookies.get("openrbi_session")
    assert cookie
    return cookie


async def login_with_mfa_enrollment(client: httpx.AsyncClient, username: str, password: str) -> str:
    """Full mandatory-MFA-enrollment login path for ADMIN/SECURITY_REVIEWER
    (app/api/auth.py's mfa_enrollment_required branch + app/api/mfa.py's
    /mfa/setup/enroll + /mfa/setup/confirm). Returns the session cookie.
    """
    r = await client.post("/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    body = r.json()
    assert body["status"] == "mfa_enrollment_required", f"expected mandatory enrollment, got {body}"
    mfa_token = body["mfa_token"]

    r = await client.post("/mfa/setup/enroll", json={"mfa_token": mfa_token})
    r.raise_for_status()
    uri = r.json()["otpauth_uri"]
    secret = dict(part.split("=") for part in uri.split("?", 1)[1].split("&"))["secret"]
    code = pyotp.TOTP(secret).now()

    r = await client.post("/mfa/setup/confirm", json={"mfa_token": mfa_token, "code": code})
    r.raise_for_status()
    cookie = r.cookies.get("openrbi_session")
    assert cookie
    return cookie


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _cleanup_test_data():
    """Sweeps up every row this test session creates, identified purely by
    the PREFIX naming convention (never by tracking individual IDs — the
    number of tables involved makes that error-prone). Runs once at the end
    of the whole test session, in FK-safe order.
    """
    yield
    async with async_session_factory() as db:
        await db.execute(
            text("UPDATE incidents SET assigned_to = NULL WHERE assigned_to IN "
                 "(SELECT id FROM users WHERE username LIKE :prefix)"),
            {"prefix": f"{PREFIX}%"},
        )
        await db.execute(
            text("DELETE FROM incidents WHERE user_id IN "
                 "(SELECT id FROM users WHERE username LIKE :prefix)"),
            {"prefix": f"{PREFIX}%"},
        )
        # security_events can reference a user, a session, and/or a
        # quarantine file — must be cleared before any of those three,
        # not just before the user row.
        await db.execute(
            text(
                "DELETE FROM security_events WHERE "
                "user_id IN (SELECT id FROM users WHERE username LIKE :prefix) "
                "OR session_id IN (SELECT id FROM browser_sessions WHERE user_id IN "
                "  (SELECT id FROM users WHERE username LIKE :prefix)) "
                "OR quarantine_file_id IN (SELECT id FROM quarantine_files WHERE user_id IN "
                "  (SELECT id FROM users WHERE username LIKE :prefix))"
            ),
            {"prefix": f"{PREFIX}%"},
        )
        await db.execute(
            text("DELETE FROM quarantine_files WHERE user_id IN "
                 "(SELECT id FROM users WHERE username LIKE :prefix) "
                 "OR reviewed_by IN (SELECT id FROM users WHERE username LIKE :prefix)"),
            {"prefix": f"{PREFIX}%"},
        )
        await db.execute(
            text("DELETE FROM browser_sessions WHERE user_id IN "
                 "(SELECT id FROM users WHERE username LIKE :prefix)"),
            {"prefix": f"{PREFIX}%"},
        )
        await db.execute(
            text("DELETE FROM recovery_codes WHERE user_id IN "
                 "(SELECT id FROM users WHERE username LIKE :prefix)"),
            {"prefix": f"{PREFIX}%"},
        )
        await db.execute(
            text("DELETE FROM user_groups WHERE user_id IN "
                 "(SELECT id FROM users WHERE username LIKE :prefix)"),
            {"prefix": f"{PREFIX}%"},
        )
        await db.execute(
            text("UPDATE policy_versions SET created_by = NULL WHERE created_by IN "
                 "(SELECT id FROM users WHERE username LIKE :prefix)"),
            {"prefix": f"{PREFIX}%"},
        )
        # group_policies has no ON DELETE CASCADE on either FK (deliberately
        # — see app/models/policy.py) — was missing here entirely, so any
        # test attaching a policy to a group (e.g. test_policy_engine.py)
        # left a dangling row that made the DELETE FROM groups/policies
        # below fail with a FK violation at session end. Matches on either
        # side's prefix since a group and its attached policy don't
        # necessarily share exactly the same test-generated name.
        await db.execute(
            text(
                "DELETE FROM group_policies WHERE "
                "group_id IN (SELECT id FROM groups WHERE name LIKE :prefix) "
                "OR policy_id IN (SELECT id FROM policies WHERE name LIKE :prefix)"
            ),
            {"prefix": f"{PREFIX}%"},
        )
        await db.execute(text("DELETE FROM groups WHERE name LIKE :prefix"), {"prefix": f"{PREFIX}%"})
        await db.execute(
            text("DELETE FROM file_policy_rules WHERE policy_version_id IN "
                 "(SELECT pv.id FROM policy_versions pv JOIN policies p ON p.id = pv.policy_id "
                 "WHERE p.name LIKE :prefix)"),
            {"prefix": f"{PREFIX}%"},
        )
        await db.execute(
            text("UPDATE policies SET current_version_id = NULL WHERE name LIKE :prefix"),
            {"prefix": f"{PREFIX}%"},
        )
        await db.execute(
            text("DELETE FROM policy_versions WHERE policy_id IN "
                 "(SELECT id FROM policies WHERE name LIKE :prefix)"),
            {"prefix": f"{PREFIX}%"},
        )
        await db.execute(text("DELETE FROM policies WHERE name LIKE :prefix"), {"prefix": f"{PREFIX}%"})
        await db.execute(text("DELETE FROM users WHERE username LIKE :prefix"), {"prefix": f"{PREFIX}%"})
        await db.commit()
