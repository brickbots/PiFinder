"""
Unit tests for the master-volume duty mapping.

``note_duty`` resolves a master level plus a per-note intent volume to an
emitted PWM duty cycle (%), clamped to the buzzer's usable 0-50% range. It
is PURE (no hardware), so the whole non-linear mapping is testable off a
board — same discipline as ``battery_bq25895.decode_registers``.
"""

import pytest

from PiFinder.sound import MASTER_DUTY, MAX_DUTY, note_duty


@pytest.mark.unit
def test_off_is_silent():
    """``Off`` mutes regardless of intent volume."""
    assert note_duty("Off", 1.0) == 0.0
    assert note_duty("Off", 0.5) == 0.0


@pytest.mark.unit
@pytest.mark.parametrize("level", ["1", "2", "3", "4", "5"])
def test_full_intent_matches_master_peak(level):
    """A full-intent (1.0) note emits exactly the level's peak duty."""
    assert note_duty(level, 1.0) == MASTER_DUTY[level]


@pytest.mark.unit
def test_intent_volume_scales_peak():
    """Intent volume scales the level's peak duty."""
    assert note_duty("5", 0.5) == MASTER_DUTY["5"] * 0.5
    assert note_duty("4", 0.25) == MASTER_DUTY["4"] * 0.25


@pytest.mark.unit
@pytest.mark.parametrize("level", list(MASTER_DUTY))
def test_rest_is_silent_at_every_level(level):
    """``volume=0`` is a rest: silent at any level."""
    assert note_duty(level, 0.0) == 0.0


@pytest.mark.unit
@pytest.mark.parametrize("vol", [1.5, 2.0, 100.0])
def test_volume_clamped_high(vol):
    """Out-of-range volume clamps to 1.0 (the level peak), never above."""
    assert note_duty("5", vol) == MASTER_DUTY["5"]


@pytest.mark.unit
@pytest.mark.parametrize("vol", [-0.1, -1.0])
def test_volume_clamped_low(vol):
    """Negative volume clamps to 0 (silent)."""
    assert note_duty("5", vol) == 0.0


@pytest.mark.unit
def test_never_exceeds_max_duty():
    """No level/volume combination ever emits above MAX_DUTY (50%)."""
    for level in MASTER_DUTY:
        for vol in (0.0, 0.5, 1.0, 5.0):
            assert note_duty(level, vol) <= MAX_DUTY


@pytest.mark.unit
@pytest.mark.parametrize("level", ["11", "", "loud"])
def test_unknown_level_is_silent(level):
    """An unknown level maps to 0 — defensive: a bad config value mutes."""
    assert note_duty(level, 1.0) == 0.0
