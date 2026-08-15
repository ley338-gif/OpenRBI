"""Seeds/tears down the throwaway accounts frontend/e2e/ needs, using the
same real `create_user` service function the admin API itself calls (see
backend/tests/conftest.py's `make_user`) — never a hand-rolled INSERT.

Run inside the backend container (see scripts/e2e-seed.sh):
    docker exec openrbi-backend-1 python /app/e2e_seed.py up
    docker exec openrbi-backend-1 python /app/e2e_seed.py down

All created rows use the PREFIX below so they're unambiguously test data,
matching backend/tests/conftest.py's own convention.
"""

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime

import pyotp
from sqlalchemy import text

from app.core.crypto import encrypt_secret
from app.db.session import async_session_factory
from app.models.system_state import SYSTEM_STATE_ID, SystemState
from app.services.users import create_user

PREFIX = "e2e_"
ADMIN_USERNAME = f"{PREFIX}admin"
ADMIN_ENROLL_USERNAME = f"{PREFIX}admin_enroll"
USER_USERNAME = f"{PREFIX}user"
PASSWORD = "E2E-Test-Password!2026"


async def up():
    async with async_session_factory() as db:
        # A completely fresh database (e.g. a throwaway CI stack that's
        # never been through the real setup wizard) has setup_required
        # still true, which makes the Admin Portal render SetupGate's
        # "Initial System Setup" wizard instead of the normal login form
        # -- no "Log in" button ever appears, and every test here would
        # hang until Playwright's own timeout. This E2E suite creates its
        # accounts directly via create_user(), bypassing POST /setup/admin
        # entirely, so nothing else ever marks the system initialized.
        # system_state.initialized only ever transitions false -> true,
        # once (app/models/system_state.py) -- deliberately never reset in
        # down() below, matching that one-way invariant.
        state = await db.get(SystemState, SYSTEM_STATE_ID)
        if state is None:
            db.add(SystemState(id=SYSTEM_STATE_ID, initialized=True, initialized_at=datetime.now(UTC)))
        elif not state.initialized:
            state.initialized = True
            state.initialized_at = datetime.now(UTC)
            db.add(state)

        # e2e_admin: pre-enrolled with a known secret, via the same
        # encrypt_secret() the real enrollment flow uses (app/services/
        # mfa.py's confirm_enrollment) — not a hand-rolled bypass of MFA,
        # just skipping the *UI* steps for tests that don't need to
        # exercise enrollment itself. This is what almost every real
        # admin login looks like (already enrolled from a prior session),
        # and it makes those tests robust to worker restarts, since a
        # UI-driven enrollment can only ever happen once per account.
        admin = await create_user(
            db, username=ADMIN_USERNAME, password=PASSWORD, role_name="ADMIN",
            group_ids=[], created_by=uuid.uuid4(),
        )
        admin_secret = pyotp.random_base32()
        admin.totp_secret_encrypted = encrypt_secret(admin_secret)
        admin.mfa_enabled = True
        db.add(admin)

        # e2e_admin_enroll: deliberately left unenrolled, for the one test
        # that exercises the real first-login mandatory-enrollment UI flow
        # end to end (QR code, confirm, one-time recovery codes).
        admin_enroll = await create_user(
            db, username=ADMIN_ENROLL_USERNAME, password=PASSWORD, role_name="ADMIN",
            group_ids=[], created_by=uuid.uuid4(),
        )

        user = await create_user(
            db, username=USER_USERNAME, password=PASSWORD, role_name="USER",
            group_ids=[], created_by=uuid.uuid4(),
        )
        await db.commit()
        print(json.dumps({
            "admin": {"username": ADMIN_USERNAME, "password": PASSWORD, "id": str(admin.id), "totp_secret": admin_secret},
            "admin_enroll": {"username": ADMIN_ENROLL_USERNAME, "password": PASSWORD, "id": str(admin_enroll.id)},
            "user": {"username": USER_USERNAME, "password": PASSWORD, "id": str(user.id)},
        }))


async def down():
    # Mirrors backend/tests/conftest.py's _cleanup_test_data ordering: FK
    # children before parents. Scoped to the e2e_ prefix only.
    async with async_session_factory() as db:
        await db.execute(text(
            "DELETE FROM security_events WHERE user_id IN "
            "(SELECT id FROM users WHERE username LIKE :p)"
        ), {"p": f"{PREFIX}%"})
        await db.execute(text(
            "DELETE FROM recovery_codes WHERE user_id IN "
            "(SELECT id FROM users WHERE username LIKE :p)"
        ), {"p": f"{PREFIX}%"})
        await db.execute(text(
            "DELETE FROM user_groups WHERE user_id IN "
            "(SELECT id FROM users WHERE username LIKE :p)"
        ), {"p": f"{PREFIX}%"})
        await db.execute(text(
            "DELETE FROM quarantine_files WHERE user_id IN "
            "(SELECT id FROM users WHERE username LIKE :p)"
        ), {"p": f"{PREFIX}%"})
        await db.execute(text(
            "DELETE FROM incidents WHERE user_id IN "
            "(SELECT id FROM users WHERE username LIKE :p)"
        ), {"p": f"{PREFIX}%"})
        await db.execute(text(
            "DELETE FROM browser_sessions WHERE user_id IN "
            "(SELECT id FROM users WHERE username LIKE :p)"
        ), {"p": f"{PREFIX}%"})
        # A policy created through the Admin Portal UI during an e2e test
        # (e.g. admin-portal.spec.ts's SESSION-resolution test) leaves a
        # policy_versions row with created_by pointing at e2e_admin — must
        # be cleared/removed before the DELETE FROM users below, same FK
        # ordering issue backend/tests/conftest.py's own cleanup had for
        # group_policies (fixed alongside this). LIKE's `_` is a SQL
        # single-char wildcard, so "e2e_%" already matches
        # "e2e-resolution-..."-style names the same way it matches
        # "e2e_admin" — no separate prefix needed.
        await db.execute(text(
            "UPDATE policy_versions SET created_by = NULL WHERE created_by IN "
            "(SELECT id FROM users WHERE username LIKE :p)"
        ), {"p": f"{PREFIX}%"})
        await db.execute(text(
            "DELETE FROM group_policies WHERE policy_id IN "
            "(SELECT id FROM policies WHERE name LIKE :p)"
        ), {"p": f"{PREFIX}%"})
        await db.execute(text(
            "DELETE FROM file_policy_rules WHERE policy_version_id IN "
            "(SELECT pv.id FROM policy_versions pv JOIN policies p ON p.id = pv.policy_id "
            "WHERE p.name LIKE :p)"
        ), {"p": f"{PREFIX}%"})
        await db.execute(text(
            "UPDATE policies SET current_version_id = NULL WHERE name LIKE :p"
        ), {"p": f"{PREFIX}%"})
        await db.execute(text(
            "DELETE FROM policy_versions WHERE policy_id IN "
            "(SELECT id FROM policies WHERE name LIKE :p)"
        ), {"p": f"{PREFIX}%"})
        await db.execute(text("DELETE FROM policies WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
        await db.execute(text("DELETE FROM users WHERE username LIKE :p"), {"p": f"{PREFIX}%"})
        await db.commit()
        print(json.dumps({"cleaned": True}))


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "up"
    asyncio.run(up() if action == "up" else down())
