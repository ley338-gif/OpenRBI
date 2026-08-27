"""Roadmap B3.1 (docs/roadmap-b3-capacity-autoscaling.md) — real
per-node capacity computation, unit-tested directly against
_compute_capacity() rather than through a live GET /v1/nodes/self call:
that function takes every host reading as a plain argument specifically
so this can be deterministic (no dependency on the actual test
runner's own CPU/RAM state), fast, and precise about which resource
(CPU vs RAM) is expected to bind in each scenario.
"""

from app.config import Settings
from app.main import _compute_capacity


def _settings(**overrides) -> Settings:
    defaults = dict(
        api_token="test-only-not-a-real-secret-0123456789abcdef",
        default_cpu_limit=2.0,
        default_ram_limit_mb=2048,
        reserved_ram_mb=512,
        capacity=None,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_ram_bound_host_reports_ram_derived_capacity():
    # 16 GiB total, 12 GiB free, 512 MB reserved -> (12288 - 512) / 2048 = 5.75 -> 5.
    # Plenty of idle CPU (32 cores, 0% used) so RAM is the binding constraint.
    breakdown = _compute_capacity(
        _settings(),
        cpu_percent=0.0,
        cpu_count=32,
        memory_total_mb=16384,
        memory_available_mb=12288,
    )
    assert breakdown.capacity == 5
    assert breakdown.bound == "ram"


def test_cpu_bound_host_reports_cpu_derived_capacity():
    # cpu_percent is psutil's 0-100 *average* across all cores, not a value
    # already scaled by cpu_count. 2 cores at a 50% average -> 100 of the
    # 200 total cpu-percent budget used -> 100% free / (2.0 * 100) = 0.5 -> 0.
    # Plenty of free RAM so CPU is the binding constraint.
    breakdown = _compute_capacity(
        _settings(),
        cpu_percent=50.0,
        cpu_count=2,
        memory_total_mb=16384,
        memory_available_mb=16000,
    )
    assert breakdown.capacity == 0
    assert breakdown.bound == "cpu"


def test_cpu_percent_is_treated_as_a_host_wide_average_not_a_flat_subtraction():
    # Regression for a real B3.1 bug: cpu_count * 100 - cpu_percent barely
    # reacts to real load on a multi-core host, because psutil's cpu_percent
    # is already a 0-100 average, not scaled by cpu_count. 8 cores at a 90%
    # average load (the host is essentially fully busy) must be reported as
    # CPU-exhausted, not as having room for more sandboxes.
    breakdown = _compute_capacity(
        _settings(),
        cpu_percent=90.0,
        cpu_count=8,
        memory_total_mb=65536,
        memory_available_mb=60000,
    )
    assert breakdown.capacity == 0


def test_high_ram_usage_lowers_capacity_than_a_lightly_loaded_host():
    # Same host, same settings, only ram usage differs -> capacity must
    # actually respond to real headroom, not just always return a
    # constant.
    light_load = _compute_capacity(
        _settings(), cpu_percent=5.0, cpu_count=8, memory_total_mb=16384, memory_available_mb=14000
    )
    heavy_load = _compute_capacity(
        _settings(), cpu_percent=5.0, cpu_count=8, memory_total_mb=16384, memory_available_mb=3000
    )
    assert heavy_load.capacity < light_load.capacity


def test_capacity_never_goes_negative_when_headroom_is_already_exhausted():
    breakdown = _compute_capacity(
        _settings(),
        cpu_percent=99.0,
        cpu_count=1,
        memory_total_mb=2048,
        memory_available_mb=100,
    )
    assert breakdown.capacity == 0


def test_explicit_ceiling_caps_a_higher_computed_value():
    breakdown = _compute_capacity(
        _settings(capacity=3),
        cpu_percent=0.0,
        cpu_count=32,
        memory_total_mb=32768,
        memory_available_mb=30000,
    )
    assert breakdown.capacity == 3
    assert breakdown.bound == "ceiling"


def test_explicit_ceiling_never_raises_a_lower_computed_value():
    # The ceiling is a maximum, never a floor -- real headroom below the
    # ceiling still wins, and the reported bound reflects the real
    # constraint, not the unused ceiling.
    breakdown = _compute_capacity(
        _settings(capacity=100),
        cpu_percent=0.0,
        cpu_count=32,
        memory_total_mb=4096,
        memory_available_mb=1000,
    )
    assert breakdown.capacity < 100
    assert breakdown.bound != "ceiling"


def test_unset_ceiling_is_uncapped():
    # No settings.capacity at all -> purely the computed value, however
    # high real headroom allows.
    breakdown = _compute_capacity(
        _settings(capacity=None),
        cpu_percent=0.0,
        cpu_count=64,
        memory_total_mb=131072,
        memory_available_mb=130000,
    )
    assert breakdown.capacity > 10  # comfortably above the pre-B3.1 flat default


def test_breakdown_exposes_both_raw_ram_and_cpu_capacity():
    # Roadmap B3.3 — an operator needs both raw numbers to see *why* one
    # resource is binding, not just the final min() result.
    breakdown = _compute_capacity(
        _settings(),
        cpu_percent=50.0,
        cpu_count=2,
        memory_total_mb=16384,
        memory_available_mb=16000,
    )
    assert breakdown.ram_capacity > breakdown.cpu_capacity
    assert breakdown.capacity == breakdown.cpu_capacity


def test_tied_ram_and_cpu_capacity_is_reported_as_ram_bound():
    # Ties go to "ram" deterministically (both are equally binding) --
    # never ambiguous or caller-order-dependent. 4 idle cores at a 1.0
    # cpu_limit give exactly 4 cpu-derived slots; 4096 MB free at a 1024 MB
    # ram_limit give exactly 4 ram-derived slots too.
    breakdown = _compute_capacity(
        _settings(default_cpu_limit=1.0, default_ram_limit_mb=1024, reserved_ram_mb=512),
        cpu_percent=0.0,
        cpu_count=4,
        memory_total_mb=4608,
        memory_available_mb=4608,
    )
    assert breakdown.ram_capacity == breakdown.cpu_capacity == 4
    assert breakdown.bound == "ram"
