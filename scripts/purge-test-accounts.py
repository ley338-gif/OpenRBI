"""Deletes the throwaway accounts a live-stack test script created, plus
every row that references them, so a run against a developer's own
`docker compose up` stack doesn't leave its probe users behind.

Run inside the backend container, after the run that created them:
    docker cp scripts/purge-test-accounts.py openrbi-backend-1:/tmp/purge-test-accounts.py
    docker exec -e PYTHONPATH=/app openrbi-backend-1 python /tmp/purge-test-accounts.py fault-

Accounts are matched purely by username prefix — the same convention as
backend/tests/conftest.py's `_cleanup_test_data` and scripts/e2e-seed.py's
`down`, whose FK-safe ordering this mirrors. Still-live browser sessions
are terminated through the real Session Agent first, so no sandbox
container outlives its row; one whose agent is unreachable is left to the
orphan reconciler. Server-side login sessions in Redis are revoked too.
"""

import asyncio
import json
import sys

import app.models  # noqa: F401 - register all mapped tables
from app.core import sessions as login_sessions
from app.db.session import async_session_factory
from app.models.browser_session import BrowserSession
from app.models.group import UserGroup
from app.models.incident import Incident
from app.models.mfa import RecoveryCode
from app.models.policy import PolicyVersion
from app.models.quarantine import QuarantineFile
from app.models.security_event import SecurityEvent
from app.models.user import User
from app.services.sessions import revoke_user_sessions
from sqlalchemy import delete, or_, select, update

# A prefix this short could match real accounts; every caller uses a
# descriptive one ("fault-", "security-rogue-check-").
MIN_PREFIX_LENGTH = 6


async def purge(prefix: str) -> None:
    async with async_session_factory() as db:
        users = (
            await db.scalars(select(User).where(User.username.startswith(prefix, autoescape=True)))
        ).all()
        user_ids = [user.id for user in users]
        sandboxes_terminated = 0
        for user in users:
            sandboxes_terminated += len(await revoke_user_sessions(db, user, actor_id=user.id))
            await login_sessions.revoke_all_sessions_for_user(user.id)

        session_ids = select(BrowserSession.id).where(BrowserSession.user_id.in_(user_ids))
        file_ids = select(QuarantineFile.id).where(
            or_(QuarantineFile.user_id.in_(user_ids), QuarantineFile.session_id.in_(session_ids))
        )
        await db.execute(update(Incident).where(Incident.assigned_to.in_(user_ids)).values(assigned_to=None))
        await db.execute(
            delete(Incident).where(
                or_(
                    Incident.user_id.in_(user_ids),
                    Incident.session_id.in_(session_ids),
                    Incident.quarantine_file_id.in_(file_ids),
                )
            )
        )
        await db.execute(
            delete(SecurityEvent).where(
                or_(
                    SecurityEvent.user_id.in_(user_ids),
                    SecurityEvent.session_id.in_(session_ids),
                    SecurityEvent.quarantine_file_id.in_(file_ids),
                )
            )
        )
        await db.execute(
            update(QuarantineFile).where(QuarantineFile.reviewed_by.in_(user_ids)).values(reviewed_by=None)
        )
        await db.execute(delete(QuarantineFile).where(QuarantineFile.id.in_(file_ids)))
        await db.execute(delete(BrowserSession).where(BrowserSession.user_id.in_(user_ids)))
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id.in_(user_ids)))
        await db.execute(delete(UserGroup).where(UserGroup.user_id.in_(user_ids)))
        await db.execute(
            update(PolicyVersion).where(PolicyVersion.created_by.in_(user_ids)).values(created_by=None)
        )
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()
        print(
            json.dumps(
                {"prefix": prefix, "users_deleted": len(user_ids), "sandboxes_terminated": sandboxes_terminated},
                sort_keys=True,
            ),
            flush=True,
        )


if __name__ == "__main__":
    if len(sys.argv) != 2 or len(sys.argv[1]) < MIN_PREFIX_LENGTH:
        raise SystemExit(f"usage: purge-test-accounts.py <username prefix, at least {MIN_PREFIX_LENGTH} chars>")
    asyncio.run(purge(sys.argv[1]))
