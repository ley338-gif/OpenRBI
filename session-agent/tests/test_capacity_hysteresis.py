"""Roadmap B3.2 (docs/roadmap-b3-capacity-autoscaling.md) — asymmetric
capacity smoothing: a drop applies immediately, a rise only after
consecutive polls sustain it. Each test constructs its own fresh
_CapacityHysteresis instance rather than touching main.py's shared
module-level one, so these stay deterministic and order-independent.
"""

from app.main import _CapacityHysteresis


def test_first_ever_call_reports_the_raw_value_unsmoothed():
    h = _CapacityHysteresis()
    assert h.apply(5, recovery_polls=3) == 5


def test_a_drop_applies_immediately():
    h = _CapacityHysteresis()
    h.apply(5, recovery_polls=3)
    assert h.apply(2, recovery_polls=3) == 2


def test_a_rise_is_held_back_until_enough_consecutive_polls_sustain_it():
    h = _CapacityHysteresis()
    h.apply(2, recovery_polls=3)
    assert h.apply(5, recovery_polls=3) == 2  # 1st consecutive higher poll — held
    assert h.apply(5, recovery_polls=3) == 2  # 2nd — still held
    assert h.apply(5, recovery_polls=3) == 5  # 3rd — now applied


def test_a_dip_during_recovery_resets_the_streak():
    h = _CapacityHysteresis()
    h.apply(2, recovery_polls=3)
    assert h.apply(5, recovery_polls=3) == 2  # 1st consecutive higher poll
    assert h.apply(2, recovery_polls=3) == 2  # dips back — resets the streak
    assert h.apply(5, recovery_polls=3) == 2  # back to 1st again, not 2nd — held
    assert h.apply(5, recovery_polls=3) == 2  # 2nd — still held
    assert h.apply(5, recovery_polls=3) == 5  # 3rd — now applied


def test_capacity_is_not_already_back_to_full_the_moment_pressure_clears():
    # Mirrors the real fault-injection scenario this phase's own DoD
    # calls for: a full host (10), a pressure event drops it to 2, the
    # pressure clears and headroom is immediately back to 10 again — but
    # the *reported* value must not jump straight back on the very next
    # poll.
    h = _CapacityHysteresis()
    h.apply(10, recovery_polls=3)
    assert h.apply(2, recovery_polls=3) == 2  # pressure hits — drops immediately
    assert h.apply(10, recovery_polls=3) == 2  # pressure clears — still held at 2
    assert h.apply(10, recovery_polls=3) == 2  # still held
    assert h.apply(10, recovery_polls=3) == 10  # sustained for long enough — recovers


def test_repeatedly_reporting_the_same_value_never_resets_or_needs_recovery():
    h = _CapacityHysteresis()
    h.apply(5, recovery_polls=3)
    for _ in range(10):
        assert h.apply(5, recovery_polls=3) == 5
