"""RBI-POST-002 — app/services/health.py::check_network_isolation is pure
filesystem-read logic (no DB, no external service), so unlike most of
this directory it needs no throwaway server, real or otherwise — a
temp-directory marker file and a monkeypatched Settings are enough to
exercise every branch honestly.
"""

import time

import pytest

from app.config import get_settings
from app.services import health


def _settings_with_marker(marker_path: str, max_staleness: float = 900.0):
    return get_settings().model_copy(
        update={
            "network_isolation_marker_file": marker_path,
            "network_isolation_max_staleness_seconds": max_staleness,
        }
    )


@pytest.mark.asyncio
async def test_missing_marker_is_not_configured_never_healthy(tmp_path, monkeypatch):
    # docker compose up alone, nobody has ever run
    # scripts/setup-network-isolation.sh — must never read as HEALTHY.
    marker = tmp_path / "does-not-exist" / "marker"
    monkeypatch.setattr(health, "get_settings", lambda: _settings_with_marker(str(marker)))
    result = await health.check_network_isolation()
    assert result.status == health.ComponentStatus.NOT_CONFIGURED


@pytest.mark.asyncio
async def test_fresh_marker_is_healthy(tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    marker.write_text(f"MARKER=openrbi-network-isolation\nAPPLIED_AT={time.time()}\nBROWSER_PLANE_SUBNET=172.30.0.0/24\n")
    monkeypatch.setattr(health, "get_settings", lambda: _settings_with_marker(str(marker)))
    result = await health.check_network_isolation()
    assert result.status == health.ComponentStatus.HEALTHY


@pytest.mark.asyncio
async def test_stale_marker_is_degraded_not_healthy(tmp_path, monkeypatch):
    # The script ran once, long ago (e.g. before a host reboot with no
    # timer installed) — must not be trusted as still-current.
    marker = tmp_path / "marker"
    marker.write_text(f"MARKER=openrbi-network-isolation\nAPPLIED_AT={time.time() - 3600}\n")
    monkeypatch.setattr(health, "get_settings", lambda: _settings_with_marker(str(marker), max_staleness=900.0))
    result = await health.check_network_isolation()
    assert result.status == health.ComponentStatus.DEGRADED


@pytest.mark.asyncio
async def test_malformed_marker_is_unavailable_never_healthy(tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    marker.write_text("not a valid marker file\n")
    monkeypatch.setattr(health, "get_settings", lambda: _settings_with_marker(str(marker)))
    result = await health.check_network_isolation()
    assert result.status == health.ComponentStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_marker_missing_required_field_is_unavailable(tmp_path, monkeypatch):
    # Content present and readable, but not a valid marker (missing
    # MARKER=/APPLIED_AT=) — must fail closed to UNAVAILABLE, not HEALTHY.
    marker = tmp_path / "marker"
    marker.write_text("SOME_OTHER_KEY=value\n")
    monkeypatch.setattr(health, "get_settings", lambda: _settings_with_marker(str(marker)))
    result = await health.check_network_isolation()
    assert result.status == health.ComponentStatus.UNAVAILABLE
