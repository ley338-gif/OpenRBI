"""State assertions used by run-fault-injection-tests.sh inside backend.

This is deliberately a thin acceptance probe, not production code.  The host
script injects real Docker/network/process faults; this module observes the
application through its real database, Redis, Session Agent and service layer.
"""

import argparse
import asyncio
import json
import uuid

from sqlalchemy import func, select

from app.core import orphan_reconciler, session_agent_client
from app.core import sessions as login_sessions
from app.core.node_enrollment_tokens import create_token
from app.db.session import async_session_factory
from app.models.browser_node import BrowserNode
from app.models.browser_session import BrowserSession
from app.models.enums import (
    BrowserNodeStatus,
    NodeEnrollmentStatus,
    SecurityEventType,
    SessionStatus,
)
from app.models.incident import Incident
from app.models.role import Role
from app.models.security_event import SecurityEvent
from app.models.user import User
from app.services import sessions as session_service
from app.services.dashboard import get_dashboard
from app.services.health import ComponentStatus, get_system_health
from app.services.nodes import (
    approve_node,
    drain_node,
    maintenance_node,
    undrain_node,
    unmaintenance_node,
)


def emit(**values) -> None:
    print(json.dumps(values, sort_keys=True), flush=True)


async def make_user(db, prefix: str = "fault") -> User:
    role = await db.scalar(select(Role).where(Role.name == "USER"))
    assert role is not None
    user = User(
        username=f"{prefix}-{uuid.uuid4().hex}",
        password_hash="fault-injection-probe-not-a-login-credential",
        role_id=role.id,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def run_grace_period() -> None:
    from app.config import get_settings

    orphan_reconciler._candidates.clear()
    orphan_reconciler._lost_candidates.clear()
    for _ in range(get_settings().orphan_reconcile_grace_cycles):
        await orphan_reconciler._reconcile_once()


async def seed_active() -> None:
    async with async_session_factory() as db:
        user = await make_user(db, "fault-active")
        browser_session = await session_service.create_session(db, user)
        await db.commit()
        token = await login_sessions.create_session(user.id, "USER")
        emit(session_id=str(browser_session.id), user_id=str(user.id), login_token=token)


async def verify_active(session_id: str, token: str | None) -> None:
    async with async_session_factory() as db:
        browser_session = await db.get(BrowserSession, uuid.UUID(session_id))
        assert browser_session is not None and browser_session.status == SessionStatus.ACTIVE
        node = await session_service.refresh_node_from_agent(db)
        await db.commit()
        managed = await session_agent_client.list_managed_sandboxes()
        assert session_id in managed
        assert node.active_sessions <= node.capacity
        token_present = None if token is None else await login_sessions.get_session(token) is not None
        emit(
            db_state=browser_session.status.value,
            container_state="RUNNING",
            worker_capacity=f"{node.active_sessions}/{node.capacity}",
            login_token_present=token_present,
        )


async def reconcile_lost(session_id: str) -> None:
    await run_grace_period()
    async with async_session_factory() as db:
        browser_session = await db.get(BrowserSession, uuid.UUID(session_id))
        assert browser_session is not None
        assert browser_session.status == SessionStatus.FAILED and browser_session.ended_at is not None
        event = await db.scalar(
            select(SecurityEvent).where(
                SecurityEvent.session_id == browser_session.id,
                SecurityEvent.event_type == SecurityEventType.SESSION_LOST_RECONCILED,
            )
        )
        assert event is not None
        managed = await session_agent_client.list_managed_sandboxes()
        assert session_id not in managed, "hard-killed container was not removed"
        node = await session_service.refresh_node_from_agent(db)
        dashboard = await get_dashboard(db)
        incident_count = await db.scalar(
            select(func.count(Incident.id)).where(Incident.session_id == browser_session.id)
        )
        assert any(w.kind == "lost_sessions" for w in dashboard.warnings)
        await db.commit()
        emit(
            db_state="FAILED",
            session_state="FAILED",
            container_state="REMOVED",
            worker_capacity=f"{node.active_sessions}/{node.capacity}",
            audit_event=event.event_type.value,
            incident_count=incident_count,
            admin_warning="lost_sessions",
            user_error="session is terminal and reconnect is rejected",
        )


async def create_orphan() -> None:
    session_id = str(uuid.uuid4())
    await session_agent_client.create_sandbox(
        session_id,
        cpu_limit=1.0,
        ram_limit_mb=512,
        pid_limit=128,
        disk_limit_mb=512,
        screen_width=1280,
        screen_height=800,
    )
    await session_agent_client.start_sandbox(session_id)
    emit(session_id=session_id)


async def reconcile_orphan(session_id: str) -> None:
    await run_grace_period()
    async with async_session_factory() as db:
        row = await db.get(BrowserSession, uuid.UUID(session_id))
        assert row is None
        event = await db.scalar(
            select(SecurityEvent).where(
                SecurityEvent.event_type == SecurityEventType.ORPHAN_SESSION_RECONCILED,
                SecurityEvent.metadata_json["session_id"].astext == session_id,
            )
        )
        assert event is not None
        managed = await session_agent_client.list_managed_sandboxes()
        assert session_id not in managed
        dashboard = await get_dashboard(db)
        assert any(w.kind == "orphan_sessions" for w in dashboard.warnings)
        node = await session_service.refresh_node_from_agent(db)
        await db.commit()
        emit(
            db_state="NO_ROW",
            session_state="ORPHAN_RECONCILED",
            container_state="REMOVED",
            worker_capacity=f"{node.active_sessions}/{node.capacity}",
            audit_event=event.event_type.value,
            incident_count=0,
            admin_warning="orphan_sessions",
            user_error="not applicable: no owning session row",
        )


async def startup_kill() -> None:
    original_wait = session_service._wait_for_display_ready

    async def signalled_wait(session_id: str, **_kwargs) -> None:
        print(f"STARTING_SESSION_ID={session_id}", flush=True)
        # Deterministic host-side window in which docker kill can land after
        # create+start and before ACTIVE is committed.
        await asyncio.sleep(3)
        await original_wait(session_id, attempts=3, delay_seconds=0.2)

    session_service._wait_for_display_ready = signalled_wait
    async with async_session_factory() as db:
        user = await make_user(db, "fault-startup")
        try:
            await session_service.create_session(db, user)
        except session_service.SessionServiceError as exc:
            await db.commit()
            row = await db.scalar(
                select(BrowserSession)
                .where(BrowserSession.user_id == user.id)
                .order_by(BrowserSession.created_at.desc())
            )
            assert row is not None and row.status == SessionStatus.FAILED
            # A failed startup performs immediate best-effort cleanup; the
            # broad managed inventory also lets reconciliation catch it if a
            # later agent interruption prevented that cleanup.
            try:
                await session_agent_client.terminate_sandbox(str(row.id))
            except session_agent_client.SessionAgentError:
                pass
            event = await db.scalar(
                select(SecurityEvent).where(
                    SecurityEvent.session_id == row.id,
                    SecurityEvent.event_type == SecurityEventType.SESSION_START_FAILED,
                )
            )
            assert event is not None
            assert str(row.id) not in await session_agent_client.list_managed_sandboxes()
            dashboard = await get_dashboard(db)
            assert any(w.kind == "session_start_failures" for w in dashboard.warnings)
            emit(
                session_id=str(row.id),
                db_state="FAILED",
                session_state="FAILED",
                container_state="REMOVED",
                audit_event=event.event_type.value,
                incident_count=0,
                admin_warning="session_start_failures",
                user_error=str(exc),
            )
            return
        raise AssertionError("startup unexpectedly reached ACTIVE before injected kill")


async def agent_unavailable() -> None:
    async with async_session_factory() as db:
        user = await make_user(db, "fault-agent-down")
        before = await db.scalar(select(func.count(BrowserSession.id)))
        try:
            await session_service.create_session(db, user)
        except session_service.NoCapacityError as exc:
            await db.rollback()
            async with async_session_factory() as health_db:
                after = await health_db.scalar(select(func.count(BrowserSession.id)))
                health = await get_system_health(health_db)
            components = {c.name: c.status for c in health.components}
            assert before == after
            assert health.status == ComponentStatus.DEGRADED
            assert components["session_agent"] == ComponentStatus.UNAVAILABLE
            emit(
                db_state="UNCHANGED",
                session_state="NOT_CREATED",
                container_state="UNKNOWN_FAIL_CLOSED",
                worker_capacity="NOT_SCHEDULABLE",
                audit_event="N/A: rejection precedes session creation",
                incident_count=0,
                admin_warning="system health DEGRADED/session_agent UNAVAILABLE",
                user_error=str(exc),
            )
            return
        raise AssertionError("session creation did not fail while agent network was interrupted")


async def node_modes(active_session_id: str) -> None:
    async with async_session_factory() as db:
        active = await db.get(BrowserSession, uuid.UUID(active_session_id))
        assert active is not None and active.status == SessionStatus.ACTIVE
        node = await session_service.refresh_node_from_agent(db)
        actor = await make_user(db, "fault-operator")

        async def scheduling_is_blocked(expected: BrowserNodeStatus) -> str:
            candidate = await make_user(db, f"fault-{expected.value.lower()}")
            try:
                await session_service.create_session(db, candidate)
            except session_service.NoCapacityError as exc:
                return str(exc)
            raise AssertionError(f"node in {expected.value} accepted a new session")

        await drain_node(db, node, actor_id=actor.id)
        drain_error = await scheduling_is_blocked(BrowserNodeStatus.DRAINING)
        assert active_session_id in await session_agent_client.list_active_sandboxes()
        dashboard = await get_dashboard(db)
        assert any(w.kind == "draining" for w in dashboard.warnings)
        await undrain_node(db, node, actor_id=actor.id)

        await maintenance_node(db, node, actor_id=actor.id)
        maintenance_error = await scheduling_is_blocked(BrowserNodeStatus.MAINTENANCE)
        assert active_session_id in await session_agent_client.list_active_sandboxes()
        dashboard = await get_dashboard(db)
        assert any(w.kind == "maintenance" for w in dashboard.warnings)
        await unmaintenance_node(db, node, actor_id=actor.id)

        required = {
            SecurityEventType.WORKER_DRAIN_ENABLED,
            SecurityEventType.WORKER_DRAIN_DISABLED,
            SecurityEventType.WORKER_MAINTENANCE_ENABLED,
            SecurityEventType.WORKER_MAINTENANCE_DISABLED,
        }
        found = set(
            (await db.execute(select(SecurityEvent.event_type).where(SecurityEvent.event_type.in_(required))))
            .scalars()
            .all()
        )
        assert required <= found
        await session_service.refresh_node_from_agent(db)
        await db.commit()
        emit(
            db_state="ONLINE after DRAINING and MAINTENANCE round trips",
            session_state="existing ACTIVE session preserved",
            container_state="RUNNING",
            worker_capacity=f"{node.active_sessions}/{node.capacity}",
            audit_event=sorted(e.value for e in required),
            incident_count=0,
            admin_warning=["draining", "maintenance"],
            user_error=[drain_error, maintenance_error],
        )


async def capacity_snapshot() -> None:
    """Roadmap B3.2 (docs/roadmap-b3-capacity-autoscaling.md) — the
    default node's own currently-reported capacity, straight from its
    real GET /v1/nodes/self (through session_agent_client, no smoothing
    or interpretation added here — the host script drives the actual
    memory-pressure fault and reads this repeatedly to observe the real
    session-agent's own hysteresis behavior). Also reports Roadmap
    B3.3's real-headroom breakdown (capacity_bound/ram_capacity/
    cpu_capacity), unsmoothed straight from the same response.
    """
    status = await session_agent_client.get_node_status()
    emit(
        capacity=status.capacity,
        capacity_bound=status.capacity_bound,
        ram_capacity=status.ram_capacity,
        cpu_capacity=status.cpu_capacity,
    )


async def capacity_exhausted_rejects_session() -> None:
    """Roadmap B3.4 — the fail-closed half of the acceptance claim: with
    real capacity genuinely at zero (driven by the host script's real
    CPU pressure, not a simulated/mocked value), a new session must be
    rejected with NoCapacityError, the same real code path
    tests/integration/test_scheduling.py's
    test_select_node_fails_closed_when_every_approved_node_is_full
    exercises with a stub agent — this call goes through the real
    Session Agent instead.
    """
    status = await session_agent_client.get_node_status()
    if status.capacity != 0:
        raise AssertionError(f"expected real capacity to be genuinely 0 under pressure, got {status.capacity}")
    async with async_session_factory() as db:
        user = await make_user(db, "fault-capacity-exhausted")
        before = await db.scalar(select(func.count(BrowserSession.id)))
        try:
            await session_service.create_session(db, user)
        except session_service.NoCapacityError as exc:
            await db.rollback()
            after = await db.scalar(select(func.count(BrowserSession.id)))
            assert before == after, "a rejected session must not leave a row behind"
            emit(
                db_state="UNCHANGED",
                session_state="NOT_CREATED",
                worker_capacity=0,
                user_error=str(exc),
            )
            return
        raise AssertionError("session creation did not fail while real capacity was genuinely exhausted")


async def token_state(token: str, expected: str) -> None:
    present = await login_sessions.get_session(token) is not None
    assert present is (expected == "present")
    emit(login_token_present=present)


async def node2_enrollment_token() -> None:
    """Roadmap B2.7 — the host script starts a real second Session Agent
    container (docker-compose.node.yml) pointed at this token; it
    self-enrolls the same way any real second node would.
    """
    token = await create_token()
    emit(enrollment_token=token)


async def node2_approve(hostname: str, endpoint_url: str) -> None:
    async with async_session_factory() as db:
        node = await db.scalar(select(BrowserNode).where(BrowserNode.hostname == hostname))
        assert node is not None and node.enrollment_status == NodeEnrollmentStatus.PENDING
        actor = await make_user(db, "fault-operator")
        await approve_node(db, node, endpoint_url=endpoint_url, actor_id=actor.id)
        await db.commit()
        emit(node_id=str(node.id))


async def node2_seed_active(hostname: str) -> None:
    """Drains the default node so create_session()'s real select_node()
    naturally lands on the named second node — proves real cross-node
    scheduling put the session there, not a hand-set node_id.
    """
    async with async_session_factory() as db:
        default = await session_service.refresh_node_from_agent(db)
        actor = await make_user(db, "fault-operator")
        await drain_node(db, default, actor_id=actor.id)
        await db.commit()

        user = await make_user(db, "fault-node2")
        browser_session = await session_service.create_session(db, user)
        await db.commit()
        assert browser_session.node_id is not None
        node = await db.get(BrowserNode, browser_session.node_id)
        assert node is not None and node.hostname == hostname, (
            f"expected session on {hostname}, landed on {node.hostname if node else None}"
        )

        await undrain_node(db, default, actor_id=actor.id)
        await db.commit()
        token = await login_sessions.create_session(user.id, "USER")
        emit(session_id=str(browser_session.id), login_token=token, node_hostname=node.hostname)


async def node2_verify_unreachable_session_failed(session_id: str) -> None:
    """Same shape as reconcile_lost(), plus the B2.5 node_unreachable tag
    that distinguishes 'the whole node went down' from 'one container on
    an otherwise-healthy node vanished'.
    """
    await run_grace_period()
    async with async_session_factory() as db:
        browser_session = await db.get(BrowserSession, uuid.UUID(session_id))
        assert browser_session is not None
        assert browser_session.status == SessionStatus.FAILED and browser_session.ended_at is not None
        event = await db.scalar(
            select(SecurityEvent)
            .where(
                SecurityEvent.session_id == browser_session.id,
                SecurityEvent.event_type == SecurityEventType.SESSION_LOST_RECONCILED,
            )
            .order_by(SecurityEvent.created_at.desc())
        )
        assert event is not None
        assert event.metadata_json is not None and event.metadata_json.get("node_unreachable") is True
        emit(db_state="FAILED", node_unreachable=True, audit_event=event.event_type.value)


async def node2_verify_survivor_unaffected(session_id: str) -> None:
    async with async_session_factory() as db:
        browser_session = await db.get(BrowserSession, uuid.UUID(session_id))
        assert browser_session is not None and browser_session.status == SessionStatus.ACTIVE
        emit(db_state=browser_session.status.value)


async def node2_verify_reschedules_onto_survivor(expected_hostname: str) -> None:
    async with async_session_factory() as db:
        node = await session_service.select_node(db)
        await db.commit()
        assert node.hostname == expected_hostname, f"expected {expected_hostname}, got {node.hostname}"
        emit(scheduled_node=node.hostname)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("args", nargs="*")
    parsed = parser.parse_args()
    commands = {
        "seed-active": lambda: seed_active(),
        "verify-active": lambda: verify_active(parsed.args[0], parsed.args[1] if len(parsed.args) > 1 else None),
        "reconcile-lost": lambda: reconcile_lost(parsed.args[0]),
        "create-orphan": lambda: create_orphan(),
        "reconcile-orphan": lambda: reconcile_orphan(parsed.args[0]),
        "startup-kill": lambda: startup_kill(),
        "agent-unavailable": lambda: agent_unavailable(),
        "node-modes": lambda: node_modes(parsed.args[0]),
        "token-state": lambda: token_state(parsed.args[0], parsed.args[1]),
        "capacity-snapshot": lambda: capacity_snapshot(),
        "capacity-exhausted-rejects-session": lambda: capacity_exhausted_rejects_session(),
        "node2-enrollment-token": lambda: node2_enrollment_token(),
        "node2-approve": lambda: node2_approve(parsed.args[0], parsed.args[1]),
        "node2-seed-active": lambda: node2_seed_active(parsed.args[0]),
        "node2-verify-unreachable-session-failed": lambda: node2_verify_unreachable_session_failed(parsed.args[0]),
        "node2-verify-survivor-unaffected": lambda: node2_verify_survivor_unaffected(parsed.args[0]),
        "node2-verify-reschedules-onto-survivor": lambda: node2_verify_reschedules_onto_survivor(parsed.args[0]),
    }
    if parsed.command not in commands:
        parser.error(f"unknown command: {parsed.command}")
    await commands[parsed.command]()


if __name__ == "__main__":
    asyncio.run(main())
