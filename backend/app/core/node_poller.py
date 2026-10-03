"""Roadmap Phase B / B1.10.1 — keeps BrowserNode telemetry current
independent of session-creation traffic. Before this, the only thing that
ever refreshed a node's status/telemetry was select_node() (called once
per session creation) or an admin loading /admin/health — an idle system
with no new sessions and no one looking at System could show arbitrarily
stale data forever. Same in-process-task pattern as
app/core/download_poller.py (single backend process in v1.0 — a real
multi-instance deployment would need this as a proper background worker,
not an in-process task per process).

Each tick refreshes the default node (the Session Agent configured in
.env, via the legacy auto-registering path) and every approved, enrolled
node over its own per-node connection (Roadmap B2), concurrently and each
in its own transaction: one unreachable node only stops its own heartbeat
from advancing (worker_health.py then reports it OFFLINE), it never
delays or rolls back the others.
"""

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.config import get_settings
from app.core.session_agent_client import SessionAgentError
from app.db.session import async_session_factory
from app.models.browser_node import BrowserNode
from app.models.enums import NodeEnrollmentStatus
from app.services.metrics_history import prune_samples, record_sample
from app.services.sessions import refresh_enrolled_node, refresh_node_from_agent

logger = logging.getLogger("openrbi.node_poller")

_task: asyncio.Task | None = None


async def _poll_default_node() -> None:
    async with async_session_factory() as db:
        node = await refresh_node_from_agent(db)
        await record_sample(db, node, prune=False)
        await db.commit()


async def _poll_enrolled_node(node_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        node = await db.get(BrowserNode, node_id)
        # Re-checked in this transaction: an admin may have revoked the
        # node since the list below was read.
        if node is None or node.enrollment_status != NodeEnrollmentStatus.APPROVED or not node.endpoint_url:
            return
        await refresh_enrolled_node(db, node)
        await record_sample(db, node, prune=False)
        await db.commit()


async def poll_once() -> None:
    async with async_session_factory() as db:
        result = await db.execute(
            select(BrowserNode.id, BrowserNode.hostname).where(
                BrowserNode.enrollment_status == NodeEnrollmentStatus.APPROVED,
                BrowserNode.endpoint_url.is_not(None),
            )
        )
        enrolled = list(result.all())

    labels = ["default node"] + [hostname for _, hostname in enrolled]
    outcomes = await asyncio.gather(
        _poll_default_node(),
        *(_poll_enrolled_node(node_id) for node_id, _ in enrolled),
        return_exceptions=True,
    )
    for label, outcome in zip(labels, outcomes, strict=True):
        if isinstance(outcome, SessionAgentError):
            # Expected during a real Session Agent outage — the node's
            # last_heartbeat simply stops advancing, and
            # app/services/worker_health.py's staleness check reports it
            # OFFLINE on its own; never a reason to stop polling (the agent
            # may come back).
            logger.warning("node telemetry poll failed for %s: %s", label, outcome)
        elif isinstance(outcome, BaseException):
            logger.error("node telemetry poll failed unexpectedly for %s", label, exc_info=outcome)

    async with async_session_factory() as db:
        await prune_samples(db)
        await db.commit()


async def _poll_loop() -> None:
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.node_poll_interval_seconds)
        try:
            await poll_once()
        except Exception:
            logger.exception("node telemetry poll failed unexpectedly")


def start() -> None:
    global _task
    if _task is not None:
        return
    _task = asyncio.create_task(_poll_loop())


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
