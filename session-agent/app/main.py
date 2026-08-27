import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import psutil
from fastapi import Depends, FastAPI

from app import enrollment
from app.api.sandboxes import router as sandboxes_router
from app.auth import require_control_plane_token
from app.build_info import BUILD_INFO
from app.config import get_settings
from app.providers.factory import get_provider


@asynccontextmanager
async def _lifespan(app: FastAPI):
    enrollment.start()
    yield
    enrollment.stop()


app = FastAPI(
    title="OpenRBI Session Agent",
    version=BUILD_INFO.version,
    description=(
        "Internal-only privileged service for browser sandbox lifecycle. "
        "Not exposed publicly; see docs/adr/0004 and 0005."
    ),
    lifespan=_lifespan,
)

app.include_router(sandboxes_router)

_PROCESS_STARTED_AT = datetime.fromtimestamp(psutil.Process(os.getpid()).create_time(), tz=UTC)


@dataclass
class _CapacityHysteresis:
    """Roadmap B3.2 (docs/roadmap-b3-capacity-autoscaling.md) — asymmetric
    smoothing on top of _compute_capacity()'s raw, instantaneous number.
    A drop is applied immediately on the very next call (fail-closed
    toward safety — never hide a real resource crunch behind smoothing).
    A rise is only applied once `recovery_polls` *consecutive* calls all
    report a value at least that high; any call in between that drops
    back to or below the currently-reported value resets the streak,
    since that's no longer a sustained recovery.

    A real object (not module-level globals) so tests can construct
    their own fresh instance instead of needing to reset shared state
    between cases — `main.py`'s own module-level `_capacity_hysteresis`
    is the one real GET /v1/nodes/self actually uses.
    """

    last_reported: int | None = None
    recovery_streak: int = 0

    def apply(self, raw: int, *, recovery_polls: int) -> int:
        if self.last_reported is None or raw <= self.last_reported:
            self.last_reported = raw
            self.recovery_streak = 0
            return raw

        # raw > last_reported: a potential recovery, not yet applied.
        self.recovery_streak += 1
        if self.recovery_streak >= recovery_polls:
            self.last_reported = raw
            self.recovery_streak = 0
        return self.last_reported


_capacity_hysteresis = _CapacityHysteresis()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", **BUILD_INFO.as_dict()}


@app.get("/v1/nodes/self", dependencies=[Depends(require_control_plane_token)])
async def node_status() -> dict[str, str | int | float | bool]:
    """Real BrowserNode self-report (capacity/active_sessions/runtime/
    version/CPU/RAM) — the control plane's poller (app/core/node_poller.py)
    and select_node() both call this to populate the BrowserNode row.
    Single-node MVP 1 still models this as a first-class, polled status
    rather than assumed-always-online (see docs/architecture.md#multi-node-readiness).

    CPU/RAM are host-wide (psutil.cpu_percent/virtual_memory), not scoped to
    this container's own cgroup — deliberately: the browser sandboxes this
    agent manages are sibling containers on the same host, so host-wide
    load is what "how loaded is this worker" actually means for an
    operator, not just this one process's own footprint.
    """
    settings = get_settings()
    provider = get_provider()
    active_sessions = await provider.count_active_sessions()
    version = await provider.runtime_version()
    image_available = await provider.sandbox_image_available(settings.sandbox_image)
    memory = psutil.virtual_memory()
    # Roadmap B3.2 fix: interval=None measures the delta since psutil's
    # *previous* call, process-wide -- when /v1/nodes/self is polled
    # rapidly and concurrently (node_poller.py, select_node() on every
    # session creation, an admin dashboard refresh, all sharing the same
    # process), that interval can be a few milliseconds, and a momentary
    # blip in that tiny window reads as a wildly misleading spike. A fixed
    # 0.1s blocking measurement is immune to caller timing entirely; run
    # off the event loop so one status check can't stall others.
    cpu_percent = await asyncio.to_thread(psutil.cpu_percent, interval=0.1)
    cpu_count = psutil.cpu_count() or 1
    breakdown = _compute_capacity(
        settings,
        cpu_percent=cpu_percent,
        cpu_count=cpu_count,
        memory_total_mb=memory.total / (1024 * 1024),
        memory_available_mb=memory.available / (1024 * 1024),
    )
    # Roadmap B3.3 — capacity_bound/ram_capacity/cpu_capacity are the raw,
    # unsmoothed breakdown for this instant: purely informational (why is
    # capacity what it is right now), so they don't go through B3.2's
    # hysteresis the way the scheduling-critical `capacity` field below
    # does -- only the number actually used for scheduling decisions needs
    # to resist flapping.
    return {
        "hostname": settings.node_name,
        "status": "ONLINE",
        "capacity": _capacity_hysteresis.apply(breakdown.capacity, recovery_polls=settings.capacity_recovery_polls),
        "capacity_bound": breakdown.bound,
        "ram_capacity": breakdown.ram_capacity,
        "cpu_capacity": breakdown.cpu_capacity,
        "active_sessions": active_sessions,
        "runtime": "docker",
        "version": version,
        "sandbox_image_available": image_available,
        "heartbeat_at": datetime.now(UTC).isoformat(),
        "cpu_percent": cpu_percent,
        "ram_total_mb": int(memory.total / (1024 * 1024)),
        "ram_used_mb": int((memory.total - memory.available) / (1024 * 1024)),
        "node_started_at": _PROCESS_STARTED_AT.isoformat(),
    }


@dataclass
class CapacityBreakdown:
    """Roadmap B3.3 (docs/roadmap-b3-capacity-autoscaling.md) — the final
    capacity number alone doesn't tell an operator *why* it's low. `bound`
    names whichever input actually decided the final `capacity`: "ram" or
    "cpu" when real headroom is the constraint, or "ceiling" when
    settings.capacity (an admin-set config value, not real headroom) is
    what's actually capping it below what the host could otherwise
    support — the dashboard (app/services/dashboard.py) only ever warns
    on the first two, never on an admin's own deliberate ceiling.
    """

    capacity: int
    ram_capacity: int
    cpu_capacity: int
    bound: str


def _compute_capacity(
    settings, *, cpu_percent: float, cpu_count: int, memory_total_mb: float, memory_available_mb: float
) -> CapacityBreakdown:
    """Roadmap B3.1 (docs/roadmap-b3-capacity-autoscaling.md) — real
    capacity derived from this host's actual free CPU/RAM headroom right
    now, using the same per-sandbox reservation the platform already
    enforces (default_cpu_limit/default_ram_limit_mb — Docker's own
    --cpus/--memory for every sandbox, SandboxConfig) as the unit, rather
    than a flat operator-configured number. Whichever resource has less
    room for another sandbox is the binding constraint — a host can be
    RAM-bound one moment and CPU-bound the next, and this always reflects
    whichever is scarcer at the instant this is called (`GET
    /v1/nodes/self`, polled by node_poller.py and select_node()).

    settings.capacity is a *ceiling* on this computed value (B3.1's own
    Decisions table) — unset (the default) leaves the computed number
    exactly as calculated; set, it caps the result but never raises it
    above what real headroom actually allows.

    Every host reading is a plain number argument, not a live psutil call
    made inside this function — keeps this pure and deterministic for
    tests/test_capacity.py, and guarantees the capacity reported in one
    /v1/nodes/self response is computed from the exact same readings as
    that response's own cpu_percent/ram_total_mb/ram_used_mb fields.
    """
    used_ram_mb = memory_total_mb - memory_available_mb
    free_ram_mb = memory_total_mb - settings.reserved_ram_mb - used_ram_mb
    ram_capacity = max(0, int(free_ram_mb // settings.default_ram_limit_mb))

    # cpu_percent is psutil.cpu_percent() without percpu=True -- already a
    # 0-100 average across every core, not a value scaled by cpu_count --
    # so the used share of the host's total cpu-percent budget
    # (0..cpu_count*100) is cpu_percent's *fraction* of that budget, not a
    # flat subtraction. (cpu_count * 100 - cpu_percent) would barely react
    # to real load on any host with more than one core.
    free_cpu_percent = max(0.0, cpu_count * (100 - cpu_percent))
    cpu_capacity = max(0, int(free_cpu_percent // (settings.default_cpu_limit * 100)))

    # Ties go to "ram" arbitrarily (both are equally binding) -- same
    # "pick a deterministic winner" spirit as select_node()'s own
    # lowest-hostname tie-break, not a claim that RAM matters more.
    bound = "ram" if ram_capacity <= cpu_capacity else "cpu"
    capacity = min(ram_capacity, cpu_capacity)
    if settings.capacity is not None and settings.capacity < capacity:
        capacity = settings.capacity
        bound = "ceiling"
    return CapacityBreakdown(capacity=capacity, ram_capacity=ram_capacity, cpu_capacity=cpu_capacity, bound=bound)
