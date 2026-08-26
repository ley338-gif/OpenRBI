"""Roadmap B2.1 (docs/adr/0023-node-enrollment-and-trust-model.md) — this
agent's own one-time registration call to the control plane. Only runs
when an operator has deliberately configured OPENRBI_AGENT_ENROLLMENT_TOKEN
(adding a second/Nth node); the default single-node case leaves it unset
and this module never does anything, matching today's behavior exactly.

Retries on a background loop (same in-process-task pattern as backend's
app/core/node_poller.py) only while the control plane is unreachable —
that's the one failure mode expected during normal startup ordering
(docker compose doesn't guarantee the backend is already up). Any actual
HTTP response — success or a clean rejection (bad/expired/reused token,
409 hostname conflict) — stops the loop; retrying those would just waste
the operator's single-use token allowance for nothing, and a rejected
enrollment needs a human to generate a fresh token anyway.
"""

import asyncio
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("openrbi.enrollment")

_task: asyncio.Task | None = None
_RETRY_SECONDS = 10


async def _try_enroll_once(settings) -> bool:
    """Returns True once the loop should stop (success or a definitive
    rejection), False to keep retrying (control plane unreachable).
    """
    async with httpx.AsyncClient(base_url=settings.control_plane_url, timeout=15.0) as client:
        try:
            # CSRFMiddleware (backend/app/core/csrf.py) issues a fresh
            # csrf_token cookie on any response to a caller that doesn't
            # already have one — this GET's only purpose is to receive
            # that cookie so it can be echoed back as X-CSRF-Token below,
            # the same double-submit dance shared/api/client.ts's
            # ensureCsrfCookie() does for a real browser caller. This
            # endpoint has no ambient-browser-credential attack surface
            # to defend against (no cookies mean anything to a browser
            # here), but CSRFMiddleware applies uniformly to every
            # mutating request with no path-based exceptions — matching
            # that instead of carving out a special case.
            health = await client.get("/health")
            health.raise_for_status()
        except (httpx.HTTPError, OSError):
            return False

        csrf_token = client.cookies.get("csrf_token")
        try:
            response = await client.post(
                "/admin/nodes/enroll",
                json={
                    "enrollment_token": settings.enrollment_token,
                    "hostname": settings.node_name,
                    "api_token": settings.api_token,
                },
                headers={"X-CSRF-Token": csrf_token} if csrf_token else {},
            )
        except (httpx.HTTPError, OSError):
            return False

    if response.status_code == 200:
        logger.warning("node enrollment succeeded for hostname=%s — awaiting admin approval", settings.node_name)
        return True
    if response.status_code in (400, 409, 429):
        logger.error(
            "node enrollment rejected (status=%s, detail=%s) — generate a fresh enrollment token and restart "
            "with it set, this agent will not retry automatically",
            response.status_code,
            response.text,
        )
        return True
    # An unexpected status (5xx, etc.) — treat as transient, keep retrying.
    return False


async def _enroll_loop() -> None:
    settings = get_settings()
    while True:
        done = await _try_enroll_once(settings)
        if done:
            return
        await asyncio.sleep(_RETRY_SECONDS)


def start() -> None:
    global _task
    settings = get_settings()
    if not settings.enrollment_token:
        return
    if _task is not None:
        return
    _task = asyncio.create_task(_enroll_loop())


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
