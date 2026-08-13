"""Roadmap Phase B / B1.10.1 — keeps BrowserNode telemetry current
independent of session-creation traffic. Before this, the only thing that
ever refreshed a node's status/telemetry was select_node() (called once
per session creation) or an admin loading /admin/health — an idle system
with no new sessions and no one looking at System could show arbitrarily
stale data forever. Same in-process-task pattern as
app/core/download_poller.py (single backend process for MVP 1 — a real
multi-instance deployment would need this as a proper background worker,
not an in-process task per process).
"""

import asyncio
import logging

from app.config import get_settings
from app.core.session_agent_client import SessionAgentError
from app.db.session import async_session_factory
from app.services.sessions import refresh_node_from_agent

logger = logging.getLogger("openrbi.node_poller")

_task: asyncio.Task | None = None


async def _poll_loop() -> None:
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.node_poll_interval_seconds)
        try:
            async with async_session_factory() as db:
                await refresh_node_from_agent(db)
                await db.commit()
        except SessionAgentError:
            # Expected during a real Session Agent outage — the node's
            # last_heartbeat simply stops advancing, and
            # app/services/worker_health.py's staleness check reports it
            # OFFLINE on its own; no special handling needed here, and
            # never treat this as a reason to stop polling (the Agent may
            # come back).
            logger.warning("node telemetry poll failed: session agent unreachable")
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
