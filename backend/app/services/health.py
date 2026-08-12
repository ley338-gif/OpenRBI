"""Aggregated health status (Phase 19 / §25): each dependency is checked
independently and never raises — a component that can't be reached reports
UNAVAILABLE rather than taking the whole endpoint down, so admins always get
a full picture instead of a 500.
"""

import os
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import clamav_client, session_agent_client
from app.core.redis import get_redis


class ComponentStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class ComponentHealth:
    name: str
    status: ComponentStatus
    detail: str | None = None


async def check_api() -> ComponentHealth:
    return ComponentHealth(name="api", status=ComponentStatus.HEALTHY)


async def check_postgres(db: AsyncSession) -> ComponentHealth:
    try:
        await db.execute(text("SELECT 1"))
        return ComponentHealth(name="postgres", status=ComponentStatus.HEALTHY)
    except Exception as exc:
        return ComponentHealth(name="postgres", status=ComponentStatus.UNAVAILABLE, detail=str(exc))


async def check_redis() -> ComponentHealth:
    try:
        pong = await get_redis().ping()
        if pong:
            return ComponentHealth(name="redis", status=ComponentStatus.HEALTHY)
        return ComponentHealth(name="redis", status=ComponentStatus.UNAVAILABLE, detail="no PONG")
    except Exception as exc:
        return ComponentHealth(name="redis", status=ComponentStatus.UNAVAILABLE, detail=str(exc))


async def check_session_agent() -> tuple[ComponentHealth, ComponentHealth, ComponentHealth]:
    """Returns (session_agent, sandbox_runtime, browser_image) — one agent
    call surfaces all three, since they're only reachable via the agent.
    """
    try:
        node = await session_agent_client.get_node_status()
    except session_agent_client.SessionAgentError as exc:
        unavailable = ComponentStatus.UNAVAILABLE
        detail = str(exc)
        return (
            ComponentHealth(name="session_agent", status=unavailable, detail=detail),
            ComponentHealth(name="sandbox_runtime", status=unavailable, detail="session agent unreachable"),
            ComponentHealth(name="browser_image", status=unavailable, detail="session agent unreachable"),
        )

    agent_health = ComponentHealth(name="session_agent", status=ComponentStatus.HEALTHY, detail=node.status)
    runtime_health = ComponentHealth(
        name="sandbox_runtime", status=ComponentStatus.HEALTHY, detail=f"{node.runtime} {node.version}"
    )
    image_health = (
        ComponentHealth(name="browser_image", status=ComponentStatus.HEALTHY)
        if node.sandbox_image_available
        else ComponentHealth(
            name="browser_image", status=ComponentStatus.UNAVAILABLE, detail="sandbox image not present on node"
        )
    )
    return agent_health, runtime_health, image_health


async def check_clamav() -> ComponentHealth:
    if not await clamav_client.ping():
        return ComponentHealth(name="clamav", status=ComponentStatus.UNAVAILABLE, detail="no PONG")
    version = await clamav_client.signature_version()
    return ComponentHealth(name="clamav", status=ComponentStatus.HEALTHY, detail=version)


async def check_quarantine_storage() -> ComponentHealth:
    settings = get_settings()
    staging_dir = settings.download_staging_dir
    probe_path = os.path.join(staging_dir, ".health-check")
    try:
        os.makedirs(staging_dir, exist_ok=True)
        with open(probe_path, "wb") as f:
            f.write(b"ok")
        os.remove(probe_path)
        return ComponentHealth(name="quarantine_storage", status=ComponentStatus.HEALTHY)
    except OSError as exc:
        return ComponentHealth(name="quarantine_storage", status=ComponentStatus.UNAVAILABLE, detail=str(exc))


@dataclass
class SystemHealth:
    status: ComponentStatus
    components: list[ComponentHealth]


async def get_system_health(db: AsyncSession) -> SystemHealth:
    agent_health, runtime_health, image_health = await check_session_agent()
    components = [
        await check_api(),
        await check_postgres(db),
        await check_redis(),
        agent_health,
        runtime_health,
        image_health,
        await check_clamav(),
        await check_quarantine_storage(),
    ]
    # Postgres/API down means the control plane itself is unusable — that's
    # a system-wide UNAVAILABLE. Any other single dependency down (ClamAV,
    # session agent, quarantine storage, ...) still leaves the API able to
    # answer requests, so it's reported as DEGRADED rather than UNAVAILABLE
    # (fail-closed behavior for the affected feature happens at the
    # scanning/session layers themselves, not by lying about this endpoint).
    by_name = {c.name: c.status for c in components}
    if by_name["api"] != ComponentStatus.HEALTHY or by_name["postgres"] != ComponentStatus.HEALTHY:
        overall = ComponentStatus.UNAVAILABLE
    elif any(c.status != ComponentStatus.HEALTHY for c in components):
        overall = ComponentStatus.DEGRADED
    else:
        overall = ComponentStatus.HEALTHY
    return SystemHealth(status=overall, components=components)
