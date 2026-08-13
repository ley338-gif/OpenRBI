"""Roadmap Phase B / B1.10.1 — the admin nodes API (app/api/admin_nodes.py)
against the real, already-running backend + Session Agent (never mocked,
matching every other integration test in this project). Covers what
existed before this work (list/drain/undrain, RBAC) plus what's new:
telemetry fields on the response, maintenance/unmaintenance, and audit
coverage for all four state-changing actions (including undrain, which
previously had no audit event at all).
"""

import pytest
from sqlalchemy import select

from app.models.browser_node import BrowserNode
from app.models.enums import BrowserNodeStatus
from app.models.security_event import SecurityEvent
from tests.conftest import login_with_mfa_enrollment, make_user


async def _get_the_node(db) -> BrowserNode:
    # Single-node MVP 1 (docs/architecture.md#multi-node-readiness) — the
    # real Session Agent this dev stack talks to has already registered
    # exactly one row by the time any test runs (either via the background
    # poller or an earlier session-creation call).
    result = await db.execute(select(BrowserNode))
    node = result.scalars().first()
    assert node is not None, "expected the real Session Agent's node row to already exist"
    return node


@pytest.mark.asyncio
async def test_non_admin_cannot_read_or_change_nodes(db, client):
    user, password = await make_user(db, role_name="USER")
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    cookie = r.cookies.get("openrbi_session")

    node = await _get_the_node(db)

    r = await client.get("/admin/nodes", cookies={"openrbi_session": cookie})
    assert r.status_code == 403
    r = await client.post(f"/admin/nodes/{node.id}/drain", cookies={"openrbi_session": cookie})
    assert r.status_code == 403
    r = await client.post(f"/admin/nodes/{node.id}/maintenance", cookies={"openrbi_session": cookie})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_node_list_includes_real_telemetry_and_computed_health(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    r = await client.get("/admin/nodes", cookies={"openrbi_session": cookie})
    assert r.status_code == 200, r.text
    nodes = r.json()
    assert len(nodes) >= 1
    node = nodes[0]
    # Real numbers from the real Session Agent's psutil report, not
    # fabricated/hardcoded — just assert they're present and sane.
    assert isinstance(node["cpu_percent"], (int, float))
    assert 0 <= node["cpu_percent"] <= 100
    assert node["ram_total_mb"] > 0
    assert 0 <= node["ram_used_mb"] <= node["ram_total_mb"]
    assert node["uptime_seconds"] >= 0
    assert node["health"] in ("HEALTHY", "DEGRADED", "DRAINING", "MAINTENANCE", "OFFLINE")
    assert "bind_password" not in node  # sanity: never leaking unrelated secrets via a shared serializer bug


@pytest.mark.asyncio
async def test_security_reviewer_can_read_but_not_change_nodes(db, client):
    reviewer, password = await make_user(db, role_name="SECURITY_REVIEWER")
    cookie = await login_with_mfa_enrollment(client, reviewer.username, password)
    node = await _get_the_node(db)

    r = await client.get("/admin/nodes", cookies={"openrbi_session": cookie})
    assert r.status_code == 200, r.text
    r = await client.get(f"/admin/nodes/{node.id}", cookies={"openrbi_session": cookie})
    assert r.status_code == 200, r.text
    r = await client.get(f"/admin/nodes/{node.id}/metrics", cookies={"openrbi_session": cookie})
    assert r.status_code == 200, r.text

    r = await client.post(f"/admin/nodes/{node.id}/drain", cookies={"openrbi_session": cookie})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_single_node_returns_404_for_unknown_id(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    import uuid as uuid_module

    r = await client.get(f"/admin/nodes/{uuid_module.uuid4()}", cookies={"openrbi_session": cookie})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_node_metrics_rejects_unknown_range_and_unknown_node(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    node = await _get_the_node(db)
    import uuid as uuid_module

    r = await client.get(f"/admin/nodes/{node.id}/metrics?range=3y", cookies={"openrbi_session": cookie})
    assert r.status_code == 400
    assert "Traceback" not in r.text

    r = await client.get(f"/admin/nodes/{uuid_module.uuid4()}/metrics", cookies={"openrbi_session": cookie})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_maintenance_round_trip_is_audited_and_blocks_scheduling(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    node = await _get_the_node(db)

    try:
        r = await client.post(f"/admin/nodes/{node.id}/maintenance", cookies={"openrbi_session": cookie})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "MAINTENANCE"
        assert r.json()["health"] == "MAINTENANCE"

        # A node in maintenance must reject new sessions with 503 — same
        # NoCapacityError path draining already used, now also covering
        # the new state.
        user, user_password = await make_user(db, role_name="USER")
        user_cookie = await client.post(
            "/auth/login", json={"username": user.username, "password": user_password}
        )
        r = await client.post("/sessions", cookies={"openrbi_session": user_cookie.cookies.get("openrbi_session")})
        assert r.status_code == 503

        result = await db.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "WORKER_MAINTENANCE_ENABLED")
        )
        assert result.scalars().first() is not None

        r = await client.post(f"/admin/nodes/{node.id}/unmaintenance", cookies={"openrbi_session": cookie})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ONLINE"

        result = await db.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "WORKER_MAINTENANCE_DISABLED")
        )
        assert result.scalars().first() is not None
    finally:
        # Never leave the real shared dev node stuck in maintenance for
        # whatever runs next.
        await db.refresh(node)
        if node.status == BrowserNodeStatus.MAINTENANCE:
            await client.post(f"/admin/nodes/{node.id}/unmaintenance", cookies={"openrbi_session": cookie})


@pytest.mark.asyncio
async def test_drain_and_undrain_are_both_audited(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    node = await _get_the_node(db)

    try:
        r = await client.post(f"/admin/nodes/{node.id}/drain", cookies={"openrbi_session": cookie})
        assert r.status_code == 200, r.text
        assert r.json()["health"] == "DRAINING"

        result = await db.execute(select(SecurityEvent).where(SecurityEvent.event_type == "WORKER_DRAIN_ENABLED"))
        assert result.scalars().first() is not None

        r = await client.post(f"/admin/nodes/{node.id}/undrain", cookies={"openrbi_session": cookie})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ONLINE"

        # Undrain previously had NO audit event at all — this is the real
        # gap this pass closes.
        result = await db.execute(select(SecurityEvent).where(SecurityEvent.event_type == "WORKER_DRAIN_DISABLED"))
        assert result.scalars().first() is not None
    finally:
        await db.refresh(node)
        if node.status == BrowserNodeStatus.DRAINING:
            await client.post(f"/admin/nodes/{node.id}/undrain", cookies={"openrbi_session": cookie})


@pytest.mark.asyncio
async def test_maintenance_is_not_undone_by_a_heartbeat_refresh(db, client):
    """The real regression this design guards against: select_node()/the
    poller must never silently overwrite an admin-set MAINTENANCE back to
    ONLINE just because the Session Agent itself always self-reports
    ONLINE.
    """
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    node = await _get_the_node(db)

    try:
        r = await client.post(f"/admin/nodes/{node.id}/maintenance", cookies={"openrbi_session": cookie})
        assert r.status_code == 200

        from app.services.sessions import refresh_node_from_agent

        await refresh_node_from_agent(db)
        await db.commit()
        await db.refresh(node)
        assert node.status == BrowserNodeStatus.MAINTENANCE
    finally:
        await db.refresh(node)
        if node.status == BrowserNodeStatus.MAINTENANCE:
            await client.post(f"/admin/nodes/{node.id}/unmaintenance", cookies={"openrbi_session": cookie})
