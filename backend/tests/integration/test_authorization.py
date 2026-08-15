"""Ownership/authorization checklist items: user A must never be able to
see or act on user B's session or files, and this holds even for an ADMIN
account, which gets no implicit ownership over anyone else's resources
(docs/quarantine.md, app/api/sessions.py, app/api/files.py).
"""

import pytest

from app.models.browser_session import BrowserSession
from app.models.enums import QuarantineStatus, ScannerStatus, SessionStatus
from app.models.quarantine import QuarantineFile

from tests.conftest import login, login_with_mfa_enrollment, make_user


async def _make_active_session(db, owner) -> BrowserSession:
    session = BrowserSession(user_id=owner.id, status=SessionStatus.ACTIVE)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def _make_released_file(db, owner, session) -> QuarantineFile:
    qf = QuarantineFile(
        session_id=session.id,
        user_id=owner.id,
        original_name="report.pdf",
        size_bytes=1024,
        sha256="0" * 64,
        status=QuarantineStatus.RELEASED,
        scanner_status=ScannerStatus.CLEAN,
        storage_object_id="/nonexistent/does-not-matter-for-this-test",
    )
    db.add(qf)
    await db.commit()
    await db.refresh(qf)
    return qf


@pytest.mark.asyncio
async def test_user_cannot_see_another_users_session(db, client):
    owner, _ = await make_user(db, role_name="USER")
    attacker, attacker_password = await make_user(db, role_name="USER")
    session = await _make_active_session(db, owner)

    cookie = await login(client, attacker.username, attacker_password)
    r = await client.get(f"/sessions/{session.id}", cookies={"openrbi_session": cookie})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_has_no_implicit_ownership_of_someone_elses_session(db, client):
    owner, _ = await make_user(db, role_name="USER")
    admin, admin_password = await make_user(db, role_name="ADMIN")
    session = await _make_active_session(db, owner)

    cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)
    # The plain /sessions/{id} endpoint is the normal-user surface — admin
    # oversight goes through /admin/sessions instead (Phase 11), so even an
    # ADMIN gets 404 here, not implicit access.
    r = await client.get(f"/sessions/{session.id}", cookies={"openrbi_session": cookie})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_see_another_users_quarantine_file(db, client):
    owner, _ = await make_user(db, role_name="USER")
    attacker, attacker_password = await make_user(db, role_name="USER")
    session = await _make_active_session(db, owner)
    qf = await _make_released_file(db, owner, session)

    cookie = await login(client, attacker.username, attacker_password)
    r = await client.get("/files/me", cookies={"openrbi_session": cookie})
    assert r.status_code == 200
    assert all(f["id"] != str(qf.id) for f in r.json())

    r = await client.post(f"/files/{qf.id}/download-token", cookies={"openrbi_session": cookie})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_cannot_request_a_download_token_for_someone_elses_file(db, client):
    owner, _ = await make_user(db, role_name="USER")
    admin, admin_password = await make_user(db, role_name="ADMIN")
    session = await _make_active_session(db, owner)
    qf = await _make_released_file(db, owner, session)

    cookie = await login_with_mfa_enrollment(client, admin.username, admin_password)
    r = await client.post(f"/files/{qf.id}/download-token", cookies={"openrbi_session": cookie})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_download_token_bound_to_issuing_user_only(db, client):
    owner, owner_password = await make_user(db, role_name="USER")
    other, other_password = await make_user(db, role_name="USER")
    session = await _make_active_session(db, owner)
    qf = await _make_released_file(db, owner, session)

    owner_cookie = await login(client, owner.username, owner_password)
    r = await client.post(f"/files/{qf.id}/download-token", cookies={"openrbi_session": owner_cookie})
    assert r.status_code == 200
    token = r.json()["token"]

    other_cookie = await login(client, other.username, other_password)
    r = await client.get(f"/files/download/{token}", cookies={"openrbi_session": other_cookie})
    # Wrong-owner and unknown-token both fail identically (401, not 403) —
    # never confirm to the caller that a *valid* token exists for someone
    # else's file.
    assert r.status_code == 401
