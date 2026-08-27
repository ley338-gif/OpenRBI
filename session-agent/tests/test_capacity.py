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
    capacity = _compute_capacity(
        _settings(),
        cpu_percent=0.0,
        cpu_count=32,
        memory_total_mb=16384,
        memory_available_mb=12288,
    )
    assert capacity == 5


def test_cpu_bound_host_reports_cpu_derived_capacity():
    # 2 cores, 50% host-wide load -> 200 - 50 = 150% free / (2.0 * 100) = 0.75 -> 0.
    # Plenty of free RAM so CPU is the binding constraint.
    capacity = _compute_capacity(
        _settings(),
        cpu_percent=50.0,
        cpu_count=2,
        memory_total_mb=16384,
        memory_available_mb=16000,
    )
    assert capacity == 0


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
    assert heavy_load < light_load


def test_capacity_never_goes_negative_when_headroom_is_already_exhausted():
    capacity = _compute_capacity(
        _settings(),
        cpu_percent=99.0,
        cpu_count=1,
        memory_total_mb=2048,
        memory_available_mb=100,
    )
    assert capacity == 0


def test_explicit_ceiling_caps_a_higher_computed_value():
    capacity = _compute_capacity(
        _settings(capacity=3),
        cpu_percent=0.0,
        cpu_count=32,
        memory_total_mb=32768,
        memory_available_mb=30000,
    )
    assert capacity == 3


def test_explicit_ceiling_never_raises_a_lower_computed_value():
    # The ceiling is a maximum, never a floor -- real headroom below the
    # ceiling still wins.
    capacity = _compute_capacity(
        _settings(capacity=100),
        cpu_percent=0.0,
        cpu_count=32,
        memory_total_mb=4096,
        memory_available_mb=1000,
    )
    assert capacity < 100


def test_unset_ceiling_is_uncapped():
    # No settings.capacity at all -> purely the computed value, however
    # high real headroom allows.
    capacity = _compute_capacity(
        _settings(capacity=None),
        cpu_percent=0.0,
        cpu_count=64,
        memory_total_mb=131072,
        memory_available_mb=130000,
    )
    assert capacity > 10  # comfortably above the pre-B3.1 flat default
