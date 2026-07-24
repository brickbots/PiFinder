"""
Unit tests for the title-bar battery indicator glyph mapping
(``UIModule._battery_icon``).

The indicator is driven off the Battery vocabulary (see
``docs/ax/battery/CONTEXT.md``): **charge status** picks the charging glyph
(the charger pulls the terminal voltage up, so ``state_of_charge_pct`` is
``None`` while charging), and otherwise the **state of charge** is quantized
into ~20% buckets with an "empty" glyph at <=10% remaining.

This exercises the pure mapping only -- no rendering, no shared state, no
hardware -- so it can construct a bare ``UIModule`` subclass that skips the
heavy UI ``__init__``.
"""

# Installs the ``_()`` gettext builtin the UI package relies on at import.
import PiFinder.i18n  # noqa: F401

import pytest

from PiFinder.types.hardware import BatteryState, ChargeStatus
from PiFinder.ui.base import UIModule


class _BareModule(UIModule):
    """UIModule with the heavy constructor skipped.

    ``_battery_icon`` only reads the class-level ``_BATT_*`` glyph constants,
    so no instance state is needed.
    """

    def __init__(self):  # noqa: D401 - deliberately skip UIModule.__init__
        pass


@pytest.fixture(scope="module")
def module() -> _BareModule:
    return _BareModule()


def _state(soc, charge_status=ChargeStatus.NOT_CHARGING) -> BatteryState:
    """A BatteryState carrying just the fields the icon mapping reads."""
    return BatteryState(
        battery_voltage=3.7,
        charge_status=charge_status,
        on_external_power=False,
        state_of_charge_pct=soc,
        charge_current_ma=0.0,
        vbus_voltage=0.0,
        sys_voltage=3.7,
        timestamp=0.0,
    )


def _blind_state(charge_status=ChargeStatus.NOT_CHARGING) -> BatteryState:
    """An ADC-blind BatteryState: every ADC-derived field is None."""
    return BatteryState(
        battery_voltage=None,
        charge_status=charge_status,
        on_external_power=False,
        state_of_charge_pct=None,
        charge_current_ma=None,
        vbus_voltage=None,
        sys_voltage=None,
        timestamp=0.0,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "soc, expected_attr",
    [
        # Empty glyph at <=10% remaining (the specified threshold).
        (0, "_BATT_EMPTY"),
        (5, "_BATT_EMPTY"),
        (10, "_BATT_EMPTY"),
        # ~20% buckets above that.
        (11, "_BATT_20"),
        (20, "_BATT_20"),
        (30, "_BATT_20"),
        (31, "_BATT_40"),
        (50, "_BATT_40"),
        (51, "_BATT_60"),
        (70, "_BATT_60"),
        (71, "_BATT_80"),
        (90, "_BATT_80"),
        (91, "_BATT_FULL"),
        (100, "_BATT_FULL"),
    ],
)
def test_discharging_quantizes_to_20pct_buckets(module, soc, expected_attr):
    """On battery (not charging), SOC maps to its 20% bucket, empty at <=10%."""
    assert module._battery_icon(_state(soc)) == getattr(module, expected_attr)


@pytest.mark.unit
@pytest.mark.parametrize(
    "charge_status", [ChargeStatus.PRE_CHARGE, ChargeStatus.FAST_CHARGING]
)
def test_charging_shows_charging_glyph(module, charge_status):
    """While charging, SOC is None and the charging glyph wins regardless."""
    assert module._battery_icon(_state(None, charge_status)) == module._BATT_CHARGING


@pytest.mark.unit
def test_charge_done_full_cell_shows_full_not_charging(module):
    """Plugged in and topped off (CHARGE_DONE) reads as a full battery.

    CHARGE_DONE is *on external power but not charging*, so SOC is a real
    number again -- this must not show the charging glyph.
    """
    assert module._battery_icon(_state(100, ChargeStatus.CHARGE_DONE)) == (
        module._BATT_FULL
    )


@pytest.mark.unit
def test_not_charging_without_estimate_fails_safe_to_full(module):
    """Defensive: SOC None while *not* charging should never crash."""
    assert module._battery_icon(_state(None)) == module._BATT_FULL


@pytest.mark.unit
def test_adc_blind_on_battery_shows_empty(module):
    """Below the ADC blind floor on battery the cell is effectively empty
    and the low-battery shutdown is imminent (ADR 0021) — the blind state
    must read as empty, never fall through to the fail-safe full glyph."""
    assert module._battery_icon(_blind_state()) == module._BATT_EMPTY


@pytest.mark.unit
@pytest.mark.parametrize(
    "charge_status", [ChargeStatus.PRE_CHARGE, ChargeStatus.FAST_CHARGING]
)
def test_adc_blind_while_charging_shows_charging_glyph(module, charge_status):
    """Deeply discharged cell on a charger: still ADC-blind, but the unit
    is recovering, not dying — the charging glyph wins."""
    assert module._battery_icon(_blind_state(charge_status)) == module._BATT_CHARGING
