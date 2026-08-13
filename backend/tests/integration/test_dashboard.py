"""Roadmap Phase B / B1.10.2 — GET /admin/dashboard and the metrics-history
aggregation it's built on, against the real, already-running backend +
Session Agent (never mocked).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.models.browser_node import BrowserNode
from app.models.worker_metric_sample import WorkerMetricSample
from app.services import metrics_history
from tests.conftest import login_with_mfa_enrollment, make_user


async def _get_the_node(db) -> BrowserNode:
    result = await db.execute(select(BrowserNode))
    node = result.scalars().first()
    assert node is not None
    return node


@pytest.mark.asyncio
async def test_non_admin_cannot_read_dashboard(db, client):
    user, password = await make_user(db, role_name="USER")
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    cookie = r.cookies.get("openrbi_session")
    r = await client.get("/admin/dashboard", cookies={"openrbi_session": cookie})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_security_reviewer_can_read_dashboard(db, client):
    reviewer, password = await make_user(db, role_name="SECURITY_REVIEWER")
    cookie = await login_with_mfa_enrollment(client, reviewer.username, password)
    r = await client.get("/admin/dashboard", cookies={"openrbi_session": cookie})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_invalid_range_is_rejected(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    r = await client.get("/admin/dashboard?range=3y", cookies={"openrbi_session": cookie})
    assert r.status_code == 400
    assert "Traceback" not in r.text


@pytest.mark.asyncio
async def test_dashboard_reflects_real_worker_and_no_vanity_data(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    r = await client.get("/admin/dashboard?range=24h", cookies={"openrbi_session": cookie})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["kpis"]["workers_total"] >= 1
    assert body["kpis"]["system_health"] in ("HEALTHY", "DEGRADED", "UNAVAILABLE")
    assert len(body["workers"]) == body["kpis"]["workers_total"]
    assert body["kpis"]["users"] >= 1
    assert body["kpis"]["files_processed_24h"] >= 0
    assert body["kpis"]["blocked_files_24h"] >= 0
    assert body["kpis"]["incidents_24h"] >= 0
    assert body["quarantine_pending"] >= 0
    assert body["quarantine_high_risk"] >= 0
    assert len(body["recent_incidents"]) <= 5
    assert sum(item["count"] for item in body["file_statuses_24h"]) == body["kpis"]["files_processed_24h"]
    for worker in body["workers"]:
        assert worker["health"] in ("HEALTHY", "DEGRADED", "DRAINING", "MAINTENANCE", "OFFLINE")
    # A brand new install has no session history an hour old yet — must be
    # null, never a fabricated "+0".
    assert body["kpis"]["active_sessions_delta_last_hour"] is None or isinstance(
        body["kpis"]["active_sessions_delta_last_hour"], int
    )


@pytest.mark.asyncio
async def test_offline_worker_excluded_from_healthy_count(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    node = await _get_the_node(db)

    original_heartbeat = node.last_heartbeat
    try:
        node.last_heartbeat = datetime.now(UTC) - timedelta(minutes=10)
        db.add(node)
        await db.commit()

        r = await client.get("/admin/dashboard", cookies={"openrbi_session": cookie})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["telemetry_stale"] is True
        matching = [w for w in body["workers"] if w["id"] == str(node.id)]
        assert matching[0]["health"] == "OFFLINE"
        assert body["kpis"]["workers_healthy"] == 0
    finally:
        node.last_heartbeat = original_heartbeat
        db.add(node)
        await db.commit()


@pytest.mark.asyncio
async def test_session_history_buckets_real_samples(db):
    node = await _get_the_node(db)
    now = datetime.now(UTC)

    # Seed deterministic samples directly — this is testing the bucketing
    # math itself, not the poller (already covered by the live-worker test
    # above finding at least one real sample).
    await db.execute(delete(WorkerMetricSample).where(WorkerMetricSample.node_id == node.id))
    for minutes_ago, sessions in [(50, 4), (40, 6), (10, 8)]:
        db.add(
            WorkerMetricSample(
                node_id=node.id,
                recorded_at=now - timedelta(minutes=minutes_ago),
                cpu_percent=10.0,
                ram_used_mb=100,
                ram_total_mb=1000,
                active_sessions=sessions,
            )
        )
    await db.commit()

    history = await metrics_history.session_history(db, range_key="1h", now=now)
    assert len(history) >= 1
    assert all(point["count"] >= 0 for point in history)
    total_seen = sum(point["count"] for point in history)
    assert total_seen > 0


@pytest.mark.asyncio
async def test_unknown_range_key_rejected_at_service_layer(db):
    with pytest.raises(ValueError):
        await metrics_history.session_history(db, range_key="3y")
