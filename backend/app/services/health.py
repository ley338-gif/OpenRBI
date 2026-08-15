"""Aggregated health status (Phase 19 / §25): each dependency is checked
independently and never raises — a component that can't be reached reports
UNAVAILABLE rather than taking the whole endpoint down, so admins always get
a full picture instead of a 500.
"""

import os
import time
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
    # network_isolation only (RBI-POST-002): the host-level setup script
    # (scripts/setup-network-isolation.sh) has never been run for this
    # deployment at all — distinct from DEGRADED (it *was* run, but not
    # recently enough to trust) so the Admin dashboard can say "not set up"
    # rather than "broken".
    NOT_CONFIGURED = "NOT_CONFIGURED"


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


async def check_network_isolation() -> ComponentHealth:
    """Reads the marker file scripts/setup-network-isolation.sh writes
    after successfully applying the DOCKER-USER iptables blocklist
    (RBI-POST-002) — a plain filesystem read, deliberately the only kind
    of check the backend container is allowed to do here, since it has no
    host/root access to inspect iptables state directly (same
    minimal-privilege boundary as the no-docker-socket-in-backend
    decision). This can only ever prove "the script ran recently enough to
    trust"; it is not a live re-read of the kernel's netfilter tables —
    that gap is the reason for the freshness window below rather than a
    one-time check, and it is documented as a known limitation in
    docs/deployment.md rather than silently overclaimed.

    Never returns HEALTHY on a missing/unreadable/stale marker — a broken
    or absent check must not be reported as if isolation were verified.
    """
    settings = get_settings()
    path = settings.network_isolation_marker_file
    try:
        with open(path, encoding="utf-8") as f:
            fields = dict(
                line.split("=", 1) for line in f.read().splitlines() if "=" in line
            )
    except FileNotFoundError:
        return ComponentHealth(
            name="network_isolation",
            status=ComponentStatus.NOT_CONFIGURED,
            detail=(
                "Browser network isolation is not verified. Do not use OpenRBI in "
                "production until scripts/setup-network-isolation.sh has been run on "
                "the Docker host — see docs/deployment.md#network-isolation."
            ),
        )
    except OSError as exc:
        return ComponentHealth(name="network_isolation", status=ComponentStatus.UNAVAILABLE, detail=str(exc))

    if fields.get("MARKER") != "openrbi-network-isolation" or "APPLIED_AT" not in fields:
        return ComponentHealth(
            name="network_isolation", status=ComponentStatus.UNAVAILABLE, detail="marker file is malformed"
        )

    try:
        applied_at = float(fields["APPLIED_AT"])
    except ValueError:
        return ComponentHealth(
            name="network_isolation", status=ComponentStatus.UNAVAILABLE, detail="marker file is malformed"
        )

    age_seconds = time.time() - applied_at
    if age_seconds > settings.network_isolation_max_staleness_seconds or age_seconds < 0:
        return ComponentHealth(
            name="network_isolation",
            status=ComponentStatus.DEGRADED,
            detail=(
                f"isolation rules were last confirmed {int(age_seconds)}s ago, exceeding the "
                f"{int(settings.network_isolation_max_staleness_seconds)}s freshness window — "
                "re-run scripts/setup-network-isolation.sh, or install "
                "scripts/systemd/openrbi-network-isolation.timer so it reruns automatically."
            ),
        )

    return ComponentHealth(name="network_isolation", status=ComponentStatus.HEALTHY)


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
        await check_network_isolation(),
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
