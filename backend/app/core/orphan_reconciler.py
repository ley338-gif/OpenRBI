"""Orphan-container reconciliation — periodically compares the Session
Agent's real, running openrbi.managed containers against BrowserSession
rows and terminates containers that have no corresponding active row,
after seeing the same orphan on two consecutive poll cycles (docs/adr/
0021). Same in-process-task pattern as app/core/node_poller.py/
download_poller.py (single backend process for MVP 1).

Root cause this exists for (see docs/adr/0021 for the full writeup):
integration tests that create a real session via
app/services/sessions.create_session() (a real Docker container through
the Session Agent) without ever calling terminate_session(), combined
with tests/conftest.py's session-scoped cleanup fixture issuing a raw
`DELETE FROM browser_sessions` instead of going through the real
terminate path — the container is left running with no DB row at all.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import get_settings
from app.core import session_agent_client
from app.core.session_agent_client import SessionAgentError
from app.db.session import async_session_factory
from app.models.browser_session import BrowserSession
from app.models.enums import SessionStatus, SecurityEventType
from app.services.security_events import record_security_event

logger = logging.getLogger("openrbi.orphan_reconciler")

# A container backed by a row in any of these statuses is doing exactly
# what it should be — never a reconciliation target. TERMINATING is
# included: that container is already being torn down by the normal
# terminate_session() path, not orphaned.
_NOT_ORPHAN_STATUSES = (
    SessionStatus.QUEUED,
    SessionStatus.STARTING,
    SessionStatus.ACTIVE,
    SessionStatus.DISCONNECTED,
    SessionStatus.ISOLATING,
    SessionStatus.ISOLATED,
    SessionStatus.TERMINATING,
)

_task = None

# session_id (str) -> number of consecutive cycles seen as an orphan.
# In-process only, like _tasks in download_poller.py — a backend restart
# simply resets the count, which is safe under this job's own fail-closed
# rule (worst case: one extra grace period before a real orphan is acted
# on again, never a false positive from stale state).
_candidates: dict[str, int] = {}


async def _reconcile_once() -> None:
    settings = get_settings()
    try:
        running_ids = await session_agent_client.list_active_sandboxes()
    except SessionAgentError:
        # Fail closed: never act on a partial/unknown view of what's
        # actually running. The candidate grace-period state is left
        # untouched so a real orphan already mid-grace-period isn't reset
        # by a single transient agent outage.
        logger.warning("orphan reconciliation skipped: session agent unreachable")
        return

    # Container labels are always our own str(session.id) (docker_provider.py's
    # _container_name), but the label is untrusted input as far as this
    # process is concerned — skip anything that isn't a well-formed UUID
    # rather than letting a malformed value blow up the DB query.
    running_uuids: dict[str, uuid.UUID] = {}
    for session_id in running_ids:
        try:
            running_uuids[session_id] = uuid.UUID(session_id)
        except (ValueError, AttributeError):
            logger.warning("skipping non-UUID session id reported by session agent: %r", session_id)
    running_ids_set = set(running_uuids)

    async with async_session_factory() as db:
        result = (
            await db.execute(select(BrowserSession).where(BrowserSession.id.in_(running_uuids.values())))
            if running_uuids
            else None
        )
        sessions_by_id = {str(s.id): s for s in result.scalars()} if result is not None else {}

        orphan_ids: set[str] = set()
        for session_id in running_ids_set:
            session = sessions_by_id.get(session_id)
            if session is not None and session.status in _NOT_ORPHAN_STATUSES:
                continue
            orphan_ids.add(session_id)

        # Drop grace-period tracking for anything that's no longer an
        # orphan this cycle (got a live DB row, or the container is gone).
        for session_id in list(_candidates):
            if session_id not in orphan_ids:
                del _candidates[session_id]

        to_terminate: list[str] = []
        for session_id in orphan_ids:
            count = _candidates.get(session_id, 0) + 1
            _candidates[session_id] = count
            if count >= settings.orphan_reconcile_grace_cycles:
                to_terminate.append(session_id)

        for session_id in to_terminate:
            del _candidates[session_id]
            session = sessions_by_id.get(session_id)
            reason = f"db_status={session.status.value}" if session is not None else "no_browser_session_row"
            try:
                await session_agent_client.terminate_sandbox(session_id)
            except SessionAgentError:
                logger.exception("failed to terminate orphaned container for session %s", session_id)
                # Keep it out of _candidates rather than looping forever on
                # a container the agent can't tear down; it will be
                # re-detected and re-enter the grace period on the next
                # cycle if it's still running.
                continue

            await record_security_event(
                db,
                SecurityEventType.ORPHAN_SESSION_RECONCILED,
                user_id=session.user_id if session is not None else None,
                session_id=session.id if session is not None else None,
                metadata={
                    "session_id": session_id,
                    "reason": reason,
                    "reconciled_at": datetime.now(UTC).isoformat(),
                },
            )
            logger.warning("terminated orphaned container for session %s (%s)", session_id, reason)

        if to_terminate:
            await db.commit()


async def _poll_loop() -> None:
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.orphan_reconcile_interval_seconds)
        try:
            await _reconcile_once()
        except Exception:
            logger.exception("orphan reconciliation cycle failed unexpectedly")


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
