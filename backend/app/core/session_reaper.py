"""DISCONNECTED-session timeout — periodically terminates sessions that have
sat DISCONNECTED (sandbox still running, nobody viewing it) for longer than
OPENRBI_SESSION_DISCONNECTED_TIMEOUT_SECONDS. Same in-process-task pattern
as app/core/orphan_reconciler.py/quarantine_retention.py.

Before this job existed, docs/session-lifecycle.md already described a
DISCONNECTED session "timing out" into TERMINATING, but nothing in the code
ever did it — every termination path needed an explicit user/admin call.
A user who simply closed the tab left their sandbox running indefinitely,
and with the default max_sessions_per_user=1 that stuck session also
blocked them from starting a new one until an admin happened to notice it
on the Sessions page (observed in production: 300+ hours).

What this deliberately does NOT do:

- Idle-ACTIVE detection. An ACTIVE session has a live display connection,
  and noVNC keeps that connection busy (framebuffer update requests) even
  with no human input, so "idle" can't be derived from anything the
  backend currently records. Timing out a session someone is actually
  looking at would be worse than the leak this fixes.
- ISOLATED sessions are never touched — isolation preserves the sandbox
  for investigation on purpose (docs/session-lifecycle.md).

The disconnect timestamp is last_activity_at, which app/api/display.py's
disconnect handler and services/sessions.disconnect_session() both stamp
at the moment a session becomes DISCONNECTED. A row that went DISCONNECTED
before that stamping existed carries its last *connect* time instead, which
is earlier — so it's reaped no later than intended, never kept forever.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from app.config import get_settings
from app.db.session import async_session_factory
from app.models.browser_session import BrowserSession
from app.models.enums import SecurityEventType, SessionStatus
from app.services.security_events import record_security_event
from app.services.sessions import SessionServiceError, terminate_session

logger = logging.getLogger("openrbi.session_reaper")

# Passed as terminate_session()'s actor_id — metadata only (a string inside
# the SESSION_TERMINATED event's JSON blob, never a foreign key), same
# sentinel approach as setup_service.BOOTSTRAP_SYSTEM_ACTOR_ID.
SESSION_REAPER_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-00000000dead")

_task = None


async def _reap_once() -> int:
    """Returns how many sessions were terminated this cycle."""
    settings = get_settings()
    timeout = settings.session_disconnected_timeout_seconds
    if timeout <= 0:
        return 0

    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=timeout)
    disconnected_since = func.coalesce(
        BrowserSession.last_activity_at, BrowserSession.started_at, BrowserSession.created_at
    )

    reaped = 0
    async with async_session_factory() as db:
        result = await db.execute(
            select(BrowserSession.id).where(
                BrowserSession.status == SessionStatus.DISCONNECTED, disconnected_since < cutoff
            )
        )
        candidate_ids = list(result.scalars())

        for session_id in candidate_ids:
            # Claim atomically: only a session that is *still* DISCONNECTED
            # and still past the cutoff at this instant moves on. A user
            # who reconnected between the SELECT above and here flipped it
            # back to ACTIVE (and re-stamped last_activity_at), so this
            # matches nothing and their session is left alone — same
            # conditional-UPDATE reasoning as app/api/display.py's
            # disconnect handler.
            claim = cast(
                "CursorResult",
                await db.execute(
                    update(BrowserSession)
                    .where(
                        BrowserSession.id == session_id,
                        BrowserSession.status == SessionStatus.DISCONNECTED,
                        disconnected_since < cutoff,
                    )
                    .values(status=SessionStatus.TERMINATING)
                    .execution_options(synchronize_session=False)
                ),
            )
            if claim.rowcount == 0:
                continue
            await db.commit()

            session = await db.get(BrowserSession, session_id, populate_existing=True)
            if session is None:
                continue
            idle_since = session.last_activity_at or session.started_at or session.created_at
            try:
                await terminate_session(db, session, actor_id=SESSION_REAPER_ACTOR_ID)
            except SessionServiceError:
                # terminate_session() already marked it FAILED (admin-
                # visible, forced-termination eligible) — commit that
                # rather than leaving it in TERMINATING limbo.
                logger.exception("failed to terminate timed-out session %s", session_id)
                await db.commit()
                continue

            await record_security_event(
                db,
                SecurityEventType.SESSION_TIMED_OUT,
                user_id=session.user_id,
                session_id=session.id,
                metadata={
                    "reason": "disconnected_timeout",
                    "disconnected_since": idle_since.isoformat() if idle_since else None,
                    "timeout_seconds": timeout,
                },
            )
            await db.commit()
            reaped += 1
            logger.info("terminated session %s after %ss DISCONNECTED", session_id, int(timeout))

    return reaped


async def _poll_loop() -> None:
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.session_reaper_interval_seconds)
        try:
            await _reap_once()
        except Exception:
            logger.exception("session reaper cycle failed unexpectedly")


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
