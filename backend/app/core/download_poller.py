import asyncio
import uuid

from app.config import get_settings
from app.db.session import async_session_factory
from app.models.browser_session import BrowserSession
from app.models.enums import SessionStatus
from app.services.downloads import process_new_downloads

# Single backend process for MVP 1 (same caveat as app/api/display.py's
# connection registry) — a real multi-instance deployment would need this
# as a proper background worker, not an in-process task per session.
_tasks: dict[uuid.UUID, asyncio.Task] = {}

_POLLABLE_STATUSES = (SessionStatus.ACTIVE, SessionStatus.DISCONNECTED)


async def _poll_loop(session_id: uuid.UUID) -> None:
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.download_poll_interval_seconds)
        async with async_session_factory() as db:
            session = await db.get(BrowserSession, session_id)
            if session is None or session.status not in _POLLABLE_STATUSES:
                return
            await process_new_downloads(db, session)


def start_polling(session_id: uuid.UUID) -> None:
    if session_id in _tasks:
        return
    _tasks[session_id] = asyncio.create_task(_poll_loop(session_id))


def stop_polling(session_id: uuid.UUID) -> None:
    task = _tasks.pop(session_id, None)
    if task is not None:
        task.cancel()
