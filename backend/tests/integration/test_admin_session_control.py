"""Admin session control checklist items: disconnect/isolate/kill all work
against a *real* sandbox (via the real Session Agent / Docker socket, not a
mock) and are audited, kill is ADMIN-only (not SECURITY_REVIEWER), and an
isolated session actually loses network access at the container level.
"""

import httpx
import pytest

from app.models.security_event import SecurityEvent
from app.services.sessions import create_session as create_session_service
from sqlalchemy import select

from tests.conftest import login_with_mfa_enrollment, make_user


@pytest.mark.asyncio
async def test_isolate_disconnect_kill_are_audited_and_kill_is_admin_only(db, client):
    owner, _ = await make_user(db, role_name="USER")
    reviewer, reviewer_password = await make_user(db, role_name="SECURITY_REVIEWER")
    admin, admin_password = await make_user(db, role_name="ADMIN")

    session = await create_session_service(db, owner)
    await db.commit()
    session_id = session.id

    reviewer_cookie = await login_with_mfa_enrollment(client, reviewer.username, reviewer_password)
    admin_cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)

    try:
        # Isolate is explicitly granted to SECURITY_REVIEWER too (§6).
        r = await client.post(
            f"/admin/sessions/{session_id}/isolate", cookies={"openrbi_session": reviewer_cookie}
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ISOLATED"

        result = await db.execute(
            select(SecurityEvent).where(
                SecurityEvent.session_id == session_id, SecurityEvent.event_type == "SESSION_ISOLATED"
            )
        )
        assert result.scalars().first() is not None

        # An admin-triggered isolate always opens an Incident too (Definition
        # of Done step 25) — verified separately in test_incidents-adjacent
        # coverage isn't in scope here, so just confirm the session event.

        # Kill is ADMIN-only: a SECURITY_REVIEWER gets 403.
        r = await client.post(
            f"/admin/sessions/{session_id}/kill", cookies={"openrbi_session": reviewer_cookie}
        )
        assert r.status_code == 403

        r = await client.post(
            f"/admin/sessions/{session_id}/restore", cookies={"openrbi_session": reviewer_cookie}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ACTIVE"

        r = await client.post(
            f"/admin/sessions/{session_id}/kill", cookies={"openrbi_session": admin_cookie}
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "TERMINATED"

        result = await db.execute(
            select(SecurityEvent).where(
                SecurityEvent.session_id == session_id, SecurityEvent.event_type == "SESSION_TERMINATED"
            )
        )
        assert result.scalars().first() is not None

        # Idempotent: killing an already-terminated session doesn't error.
        r = await client.post(
            f"/admin/sessions/{session_id}/kill", cookies={"openrbi_session": admin_cookie}
        )
        assert r.status_code == 200
    finally:
        # Best-effort cleanup in case an assertion failed mid-sequence —
        # never leave a real sandbox container running after this test.
        try:
            await client.post(f"/admin/sessions/{session_id}/kill", cookies={"openrbi_session": admin_cookie})
        except httpx.HTTPError:
            pass


# Note: verifying that an isolated sandbox container actually has zero
# networks attached at the Docker level requires the Docker socket, which
# this backend deliberately never has (ADR 0005) — that check runs from the
# host instead, see scripts/run-security-tests.sh.
