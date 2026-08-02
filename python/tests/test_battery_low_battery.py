"""
Unit tests for the low-battery shutdown debounce and the advisory
warning thresholds (ADR 0021).

Both are PURE (no hardware, no clock, no queues), following the module's
``plan_charging_writes`` testing pattern:

* ``LowBatteryShutdownTrigger`` counts consecutive ADC-blind polls while
  on battery and fires once per sustained blind episode. It keys on the
  ADC-validity signal only — the estimated state of charge never feeds it.
* ``LowBatteryWarner`` watches the estimated state of charge fall through
  the 10%/5% thresholds, once per discharge, on battery only; the
  crossings latch and only external power re-arms them.
"""

import pytest

from PiFinder.battery_bq25895 import (
    LOW_BATTERY_SHUTDOWN_POLLS,
    LOW_BATTERY_WARNING_PCTS,
    LowBatteryShutdownTrigger,
    LowBatteryWarner,
)


@pytest.mark.unit
def test_adr_0021_constants():
    """Pin the ADR 0021 contract: a 3-5 poll debounce (~15-25 s) and
    warnings at 10% and 5%."""
    assert 3 <= LOW_BATTERY_SHUTDOWN_POLLS <= 5
    assert LOW_BATTERY_WARNING_PCTS == (10, 5)


# --- LowBatteryShutdownTrigger ---


@pytest.mark.unit
def test_trigger_fires_after_n_consecutive_blind_polls():
    """N consecutive blind polls on battery fire the trigger — exactly at
    the Nth, not before. A unit *booted* on battery below the floor hits
    this straight from poll one (correct per ADR 0021)."""
    trigger = LowBatteryShutdownTrigger()
    for _ in range(LOW_BATTERY_SHUTDOWN_POLLS - 1):
        assert trigger.update(adc_blind=True, on_external_power=False) is False
    assert trigger.update(adc_blind=True, on_external_power=False) is True


@pytest.mark.unit
def test_trigger_fires_once_per_blind_episode():
    """Past the threshold the streak keeps growing without re-firing, so
    the monitor requests shutdown exactly once."""
    trigger = LowBatteryShutdownTrigger()
    fired = [
        trigger.update(adc_blind=True, on_external_power=False)
        for _ in range(LOW_BATTERY_SHUTDOWN_POLLS + 5)
    ]
    assert fired.count(True) == 1
    assert fired[LOW_BATTERY_SHUTDOWN_POLLS - 1] is True


@pytest.mark.unit
def test_sane_read_resets_the_debounce():
    """Conversions fail *intermittently* in the 3.50-3.55 V twilight — a
    single blind read means nothing, and any sane read restarts the
    debounce from zero."""
    trigger = LowBatteryShutdownTrigger()
    for _ in range(LOW_BATTERY_SHUTDOWN_POLLS - 1):
        trigger.update(adc_blind=True, on_external_power=False)
    assert trigger.update(adc_blind=False, on_external_power=False) is False
    # A fresh full debounce is needed after the sane read.
    for _ in range(LOW_BATTERY_SHUTDOWN_POLLS - 1):
        assert trigger.update(adc_blind=True, on_external_power=False) is False
    assert trigger.update(adc_blind=True, on_external_power=False) is True


@pytest.mark.unit
def test_external_power_inhibits_and_resets():
    """Blind reads on external power never shut down — a deeply
    discharged unit on a charger must charge. They also reset the streak,
    so pulling the cable restarts the full debounce."""
    trigger = LowBatteryShutdownTrigger()
    for _ in range(LOW_BATTERY_SHUTDOWN_POLLS - 1):
        trigger.update(adc_blind=True, on_external_power=False)
    assert trigger.update(adc_blind=True, on_external_power=True) is False
    for _ in range(LOW_BATTERY_SHUTDOWN_POLLS - 1):
        assert trigger.update(adc_blind=True, on_external_power=False) is False
    assert trigger.update(adc_blind=True, on_external_power=False) is True


@pytest.mark.unit
def test_trigger_never_fires_on_sustained_external_power():
    """However long the unit sits blind on a charger, no shutdown."""
    trigger = LowBatteryShutdownTrigger()
    assert not any(
        trigger.update(adc_blind=True, on_external_power=True) for _ in range(50)
    )


@pytest.mark.unit
def test_trigger_custom_poll_count():
    trigger = LowBatteryShutdownTrigger(polls=2)
    assert trigger.update(adc_blind=True, on_external_power=False) is False
    assert trigger.update(adc_blind=True, on_external_power=False) is True


# --- LowBatteryWarner ---


@pytest.mark.unit
def test_warns_once_at_each_threshold_during_discharge():
    """A slow discharge warns exactly once at 10% and once at 5%."""
    warner = LowBatteryWarner()
    socs = (50, 30, 12, 11, 10, 9, 8, 6, 5, 4, 3)
    fired = [warner.update(soc, on_external_power=False) for soc in socs]
    assert fired == [None, None, None, None, 10, None, None, None, 5, None, None]


@pytest.mark.unit
def test_fast_drop_through_both_thresholds_warns_most_severe_once():
    """Dropping straight through 10% and 5% between samples yields one
    warning — the most severe — not two popups fighting each other."""
    warner = LowBatteryWarner()
    assert warner.update(12, on_external_power=False) is None
    assert warner.update(4, on_external_power=False) == 5
    assert warner.update(3, on_external_power=False) is None


@pytest.mark.unit
def test_quantisation_jitter_does_not_refire():
    """One BATV LSB (20 mV) is ~3 SoC points near the flat knee of the
    discharge curve, and load transients swing several LSBs. However far
    the estimate bounces back up mid-discharge, a fired threshold stays
    quiet."""
    warner = LowBatteryWarner()
    assert warner.update(10, on_external_power=False) == 10
    for soc in (13, 9, 16, 8, 23, 10, 9):
        assert warner.update(soc, on_external_power=False) is None


@pytest.mark.unit
def test_climb_never_rearms_within_a_discharge():
    """Crossings latch for the whole discharge: even a large recovery of
    the estimate does not re-arm a fired threshold — only external power
    does. (The first cut re-armed on a 2-point climb; field data showed
    quantisation noise re-firing the earcon ~90 times per discharge.)"""
    warner = LowBatteryWarner()
    assert warner.update(10, on_external_power=False) == 10
    assert warner.update(50, on_external_power=False) is None
    assert warner.update(10, on_external_power=False) is None
    assert warner.update(9, on_external_power=False) is None


# Published state-of-charge samples from the 2026-07-24 bench discharge
# (unit pf4-dev, 20:00-21:15, every 12th telemetry row ≈ one per minute):
# the final 75 minutes before the blind-floor shutdown, showing the real
# quantisation bounce across the 10% and 5% thresholds. The shipped
# 2-point hysteresis re-fired 93 warnings on this discharge.
# fmt: off
FIELD_SOC_TAIL_2026_07_24 = (
    19, 16, 23, 19, 16, 23, 13, 19, 19, 16, 13, 13, 16, 13, 16, 16, 10,
    16, 16, 16, 13, 13, 13, 13, 16, 10, 13, 13, 13, 16, 13, 10, 13, 13,
    13, 8, 10, 10, 8, 10, 10, 10, 10, 10, 10, 13, 8, 10, 4, 10, 6,
    8, 8, 8, 6, 8, 6, 4, 6, 10, 8, 4, 6, 6, 4, 6, 4, 4,
    6, 8, 4, 4, 0,
)
# fmt: on


@pytest.mark.unit
def test_field_discharge_tail_warns_exactly_twice():
    """Regression on the real 2026-07-24 discharge tail: exactly one 10%
    and one 5% warning across the whole noisy descent."""
    warner = LowBatteryWarner()
    fires = [
        warner.update(soc, on_external_power=False) for soc in FIELD_SOC_TAIL_2026_07_24
    ]
    assert [f for f in fires if f is not None] == [10, 5]


@pytest.mark.unit
def test_field_discharge_repeats_after_a_charge():
    """The same field tail warns afresh after a charge — the latch is
    per-discharge, not forever."""
    warner = LowBatteryWarner()
    for soc in FIELD_SOC_TAIL_2026_07_24:
        warner.update(soc, on_external_power=False)
    assert warner.update(None, on_external_power=True) is None
    fires = [
        warner.update(soc, on_external_power=False) for soc in FIELD_SOC_TAIL_2026_07_24
    ]
    assert [f for f in fires if f is not None] == [10, 5]


@pytest.mark.unit
def test_blind_twilight_does_not_refire():
    """Conversions fail intermittently just above the blind floor, so a
    dying battery interleaves blind (SoC None) and sane ~1% polls for
    many minutes. A None estimate suppresses warnings but must NOT
    re-arm — otherwise the 5% warning would re-fire on every sane poll
    of the twilight."""
    warner = LowBatteryWarner()
    assert warner.update(1, on_external_power=False) == 5
    for soc in (None, 1, None, 1, None, 2, None, 0):
        assert warner.update(soc, on_external_power=False) is None


@pytest.mark.unit
def test_charging_rearms_for_next_discharge():
    """A charge (SoC None while on external power) re-arms every
    threshold, so the next discharge warns afresh."""
    warner = LowBatteryWarner()
    assert warner.update(9, on_external_power=False) == 10
    assert warner.update(None, on_external_power=True) is None
    assert warner.update(9, on_external_power=False) == 10


@pytest.mark.unit
def test_external_power_suppresses_and_rearms():
    """Warnings are on-battery only. On external power with a real
    estimate (charge done), nothing fires — however low — and the
    thresholds re-arm for the next discharge."""
    warner = LowBatteryWarner()
    assert warner.update(9, on_external_power=False) == 10
    assert warner.update(8, on_external_power=True) is None
    assert warner.update(9, on_external_power=False) == 10


@pytest.mark.unit
def test_no_warning_above_thresholds():
    warner = LowBatteryWarner()
    assert all(
        warner.update(soc, on_external_power=False) is None
        for soc in range(100, 10, -1)
    )
