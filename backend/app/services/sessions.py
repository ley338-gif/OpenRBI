import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import download_poller, session_agent_client
from app.core.session_agent_client import SessionAgentError
from app.models.browser_node import BrowserNode
from app.models.browser_session import BrowserSession
from app.models.enums import (
    BrowserNodeStatus,
    IncidentSeverity,
    IncidentStatus,
    SecurityEventType,
    SessionStatus,
)
from app.models.incident import Incident
from app.models.user import User
from app.services.policy_engine import resolve_clipboard_policy, resolve_session_resolution
from app.services.security_events import record_security_event


class SessionServiceError(RuntimeError):
    pass


class NoCapacityError(SessionServiceError):
    pass


class QuotaExceededError(SessionServiceError):
    pass


async def _wait_for_display_ready(
    session_id: str, *, attempts: int = 15, delay_seconds: float = 0.5
) -> None:
    """The container starting (docker's container.start()) and its VNC
    server actually accepting connections (Xvfb -> x11vnc booting inside
    the entrypoint) are not the same moment — connecting immediately after
    session creation intermittently failed with a real race condition
    caught during end-to-end testing. Don't report a session ACTIVE until
    the display path is actually usable.
    """
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            info = await session_agent_client.get_display_info(session_id)
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(info.host, info.port), timeout=delay_seconds
            )
            writer.close()
            return
        except (SessionAgentError, OSError, asyncio.TimeoutError) as exc:
            last_error = exc
            await asyncio.sleep(delay_seconds)
    raise SessionAgentError(f"display never became ready: {last_error}")


async def refresh_node_from_agent(db: AsyncSession) -> BrowserNode:
    """Refreshes the (single, in MVP 1) BrowserNode row from the Session
    Agent's live self-report (status/capacity/active_sessions/runtime/
    version/CPU/RAM — Roadmap B1.10.1) and returns it, without judging
    whether it's usable for scheduling — that's select_node()'s job below.
    Shared by select_node() (refreshed on every session creation) and
    app/core/node_poller.py (refreshed on a fixed interval regardless of
    session traffic, so telemetry doesn't go stale between creations).
    Raises SessionAgentError, not NoCapacityError — callers that care about
    scheduling wrap this; the poller doesn't.
    """
    status = await session_agent_client.get_node_status()

    result = await db.execute(select(BrowserNode).where(BrowserNode.hostname == status.hostname))
    node = result.scalar_one_or_none()
    if node is None:
        node = BrowserNode(hostname=status.hostname)
        db.add(node)

    # DRAINING/MAINTENANCE are admin-set scheduling gates (project brief
    # §23, extended by Roadmap B1.10.1), not something the Session Agent
    # itself knows about or reports — it will always self-report ONLINE.
    # Don't let this heartbeat refresh silently undo an admin's drain or
    # maintenance hold; only overwrite status when it's neither.
    if node.status not in (BrowserNodeStatus.DRAINING, BrowserNodeStatus.MAINTENANCE):
        node.status = BrowserNodeStatus(status.status)
    node.capacity = status.capacity
    node.active_sessions = status.active_sessions
    node.runtime = status.runtime
    node.version = status.version
    node.cpu_percent = status.cpu_percent
    node.ram_total_mb = status.ram_total_mb
    node.ram_used_mb = status.ram_used_mb
    node.node_started_at = status.node_started_at
    node.last_heartbeat = datetime.now(UTC)
    await db.flush()
    return node


async def select_node(db: AsyncSession) -> BrowserNode:
    """The abstract scheduling seam docs/architecture.md describes —
    trivial today, but callers never assume a specific node, so real
    multi-node selection can replace this body later without changing
    callers.
    """
    try:
        node = await refresh_node_from_agent(db)
    except SessionAgentError as exc:
        raise NoCapacityError(f"session agent unavailable: {exc}") from exc

    if node.status != BrowserNodeStatus.ONLINE:
        raise NoCapacityError(f"node {node.hostname} is {node.status.value}, not accepting new sessions")
    if node.active_sessions >= node.capacity:
        raise NoCapacityError(f"node {node.hostname} is at capacity ({node.active_sessions}/{node.capacity})")

    return node


async def count_active_sessions_for_user(db: AsyncSession, user_id: uuid.UUID) -> int:
    active_statuses = (
        SessionStatus.QUEUED,
        SessionStatus.STARTING,
        SessionStatus.ACTIVE,
        SessionStatus.DISCONNECTED,
        SessionStatus.ISOLATING,
        SessionStatus.ISOLATED,
    )
    result = await db.execute(
        select(func.count())
        .select_from(BrowserSession)
        .where(BrowserSession.user_id == user_id, BrowserSession.status.in_(active_statuses))
    )
    return result.scalar_one()


async def create_session(db: AsyncSession, user: User) -> BrowserSession:
    """Full orchestration: quota check -> node selection -> DB row ->
    session-agent create+start -> ACTIVE. Fails closed at every step: any
    failure leaves the row (if created) in FAILED rather than silently
    discarded, and never leaves a sandbox running without a corresponding
    row or vice versa as far as this function's own actions are concerned.
    """
    settings = get_settings()
    active_count = await count_active_sessions_for_user(db, user.id)
    if active_count >= settings.max_sessions_per_user:
        raise QuotaExceededError(
            f"user already has {active_count} active session(s), limit is {settings.max_sessions_per_user}"
        )

    node = await select_node(db)  # raises NoCapacityError, propagates as 503
    resolution = await resolve_session_resolution(db, user.id)
    clipboard_mode = await resolve_clipboard_policy(db, user.id)

    session = BrowserSession(
        user_id=user.id,
        node_id=node.id,
        status=SessionStatus.QUEUED,
        screen_width=resolution.width,
        screen_height=resolution.height,
        clipboard_mode=clipboard_mode,
    )
    db.add(session)
    await db.flush()  # assigns session.id

    session.status = SessionStatus.STARTING
    await db.flush()

    try:
        await session_agent_client.create_sandbox(
            str(session.id),
            cpu_limit=float(session.cpu_limit),
            ram_limit_mb=session.ram_limit_mb,
            pid_limit=session.pid_limit,
            disk_limit_mb=session.disk_limit_mb,
            screen_width=session.screen_width,
            screen_height=session.screen_height,
        )
        await session_agent_client.start_sandbox(str(session.id))
        await _wait_for_display_ready(str(session.id))
    except SessionAgentError as exc:
        session.status = SessionStatus.FAILED
        await db.flush()
        raise SessionServiceError(f"failed to start sandbox: {exc}") from exc

    session.status = SessionStatus.ACTIVE
    session.started_at = datetime.now(UTC)
    session.last_activity_at = session.started_at
    await record_security_event(db, SecurityEventType.SESSION_STARTED, user_id=user.id, session_id=session.id)
    await db.flush()
    download_poller.start_polling(session.id)
    return session


async def terminate_session(db: AsyncSession, session: BrowserSession, *, actor_id: uuid.UUID) -> None:
    """Idempotent from the caller's perspective too: terminating an
    already-TERMINATED session is a no-op success, matching the
    session-agent's own idempotent terminate (docs/session-lifecycle.md).
    """
    if session.status == SessionStatus.TERMINATED:
        return

    session.status = SessionStatus.TERMINATING
    await db.flush()
    download_poller.stop_polling(session.id)

    try:
        await session_agent_client.terminate_sandbox(str(session.id))
    except SessionAgentError as exc:
        session.status = SessionStatus.FAILED
        await db.flush()
        raise SessionServiceError(f"failed to terminate sandbox: {exc}") from exc

    session.status = SessionStatus.TERMINATED
    session.ended_at = datetime.now(UTC)
    await record_security_event(
        db, SecurityEventType.SESSION_TERMINATED, user_id=session.user_id, session_id=session.id,
        metadata={"actor": str(actor_id)},
    )
    await db.flush()


_LIVE_STATUSES = (
    SessionStatus.QUEUED,
    SessionStatus.STARTING,
    SessionStatus.ACTIVE,
    SessionStatus.DISCONNECTED,
    SessionStatus.ISOLATING,
    SessionStatus.ISOLATED,
)


async def revoke_user_sessions(db: AsyncSession, user: User, *, actor_id: uuid.UUID) -> list[BrowserSession]:
    """Roadmap B1.10.4 — terminate every live session a user currently has,
    as one admin action from the User Detail page. Reuses terminate_session()
    per session (so each one still gets its own idempotent-terminate
    behavior and its own SESSION_TERMINATED event), then records one
    additional USER_SESSIONS_REVOKED event summarizing the batch — a
    reviewer should be able to see both "this session ended" and "an admin
    revoked this user's sessions" without inferring the latter from a run
    of same-actor SESSION_TERMINATED events.

    A session that fails to terminate (SessionServiceError, e.g. the
    sandbox runtime is unreachable) is skipped, not fatal to the rest of
    the batch — the caller gets back only the sessions that actually
    terminated.
    """
    result = await db.execute(
        select(BrowserSession).where(BrowserSession.user_id == user.id, BrowserSession.status.in_(_LIVE_STATUSES))
    )
    sessions = list(result.scalars())
    terminated: list[BrowserSession] = []
    for session in sessions:
        try:
            await terminate_session(db, session, actor_id=actor_id)
        except SessionServiceError:
            continue
        terminated.append(session)

    if terminated:
        await record_security_event(
            db, SecurityEventType.USER_SESSIONS_REVOKED, user_id=user.id,
            metadata={"actor": str(actor_id), "session_count": len(terminated)},
        )
        await db.flush()
    return terminated


async def isolate_session(db: AsyncSession, session: BrowserSession, *, actor_id: uuid.UUID) -> None:
    """Network egress DENY ALL (enforced by the Session Agent disconnecting
    the sandbox from every network it's on, Phase 6) while the sandbox
    itself keeps running for investigation (docs/session-lifecycle.md).
    Always creates an Incident, not just a security event — an admin
    choosing to isolate a session is a deliberate, rare action, not a
    high-frequency automatic trigger, so there's no alert-fatigue concern
    here (contrast with e.g. repeated NETWORK_ACCESS_BLOCKED events, which
    are aggregated rather than one-incident-each).
    """
    if session.status not in (SessionStatus.ACTIVE, SessionStatus.DISCONNECTED):
        raise SessionServiceError(f"cannot isolate a session in status {session.status.value}")

    session.status = SessionStatus.ISOLATING
    await db.flush()

    try:
        await session_agent_client.isolate_sandbox(str(session.id))
    except SessionAgentError as exc:
        session.status = SessionStatus.FAILED
        await db.flush()
        raise SessionServiceError(f"failed to isolate sandbox: {exc}") from exc

    session.status = SessionStatus.ISOLATED
    await record_security_event(
        db, SecurityEventType.SESSION_ISOLATED, user_id=session.user_id, session_id=session.id,
        metadata={"actor": str(actor_id)},
    )
    db.add(
        Incident(
            severity=IncidentSeverity.MEDIUM,
            status=IncidentStatus.NEW,
            title="Browser session isolated by admin",
            description=(
                f"Session {session.id} for user {session.user_id} was isolated by an administrator "
                "(network egress, clipboard, and file transfer denied; sandbox preserved for review)."
            ),
            user_id=session.user_id,
            session_id=session.id,
        )
    )
    await db.flush()


async def restore_session(db: AsyncSession, session: BrowserSession, *, actor_id: uuid.UUID) -> None:
    """Reactivating a previously isolated session is logged distinctly from
    the original isolation (project brief §9: "Beides muss protokolliert
    werden").
    """
    if session.status != SessionStatus.ISOLATED:
        raise SessionServiceError(f"cannot restore a session in status {session.status.value}")

    try:
        await session_agent_client.restore_sandbox(str(session.id))
    except SessionAgentError as exc:
        session.status = SessionStatus.FAILED
        await db.flush()
        raise SessionServiceError(f"failed to restore sandbox: {exc}") from exc

    session.status = SessionStatus.ACTIVE
    await record_security_event(
        db, SecurityEventType.SESSION_RESTORED, user_id=session.user_id, session_id=session.id,
        metadata={"actor": str(actor_id)},
    )
    await db.flush()


async def disconnect_session(db: AsyncSession, session: BrowserSession, *, actor_id: uuid.UUID) -> None:
    """Admin-forced disconnect: drops the remote-display connection only —
    the sandbox is untouched and the user can reconnect (docs/session-
    lifecycle.md). The actual websocket, if one is open, is closed by the
    caller (app/api/admin_sessions.py) via the in-process connection
    registry in app/api/display.py; this just records the state/event.
    """
    if session.status not in (SessionStatus.ACTIVE, SessionStatus.DISCONNECTED):
        raise SessionServiceError(f"cannot disconnect a session in status {session.status.value}")

    session.status = SessionStatus.DISCONNECTED
    await record_security_event(
        db, SecurityEventType.SESSION_DISCONNECTED, user_id=session.user_id, session_id=session.id,
        metadata={"actor": str(actor_id)},
    )
    await db.flush()
