"""
Unit tests for the state-of-charge estimate.

``estimate_soc`` interpolates the SOC_LUT discharge curve and clamps to
0-100. It is a rough UI-only estimate (the BQ25895 has no fuel gauge),
and ``decode_registers`` returns ``None`` for it while charging.
"""

import pytest

from PiFinder.battery_bq25895 import SOC_LUT, decode_registers, estimate_soc


@pytest.mark.unit
@pytest.mark.parametrize("voltage,pct", SOC_LUT)
def test_estimate_soc_at_knots(voltage, pct):
    """At every LUT knot the estimate is exactly the tabulated percent."""
    assert estimate_soc(voltage) == pct


@pytest.mark.unit
@pytest.mark.parametrize(
    "voltage,expected",
    [
        (3.62, 8),  # between (3.594, 5) and (3.643, 10): frac ~0.53 -> 8%
        (3.70, 18),  # between (3.681, 15) and (3.736, 25): frac ~0.35 -> 18%
        (3.90, 65),  # between (3.834, 50) and (3.947, 75): frac ~0.58 -> 65%
        (4.00, 92),  # between (3.983, 90) and (4.060, 100): frac ~0.22 -> 92%
    ],
)
def test_estimate_soc_interpolates(voltage, expected):
    assert estimate_soc(voltage) == expected


@pytest.mark.unit
@pytest.mark.parametrize("voltage", [3.54, 3.0, 0.0, -1.0])
def test_estimate_soc_clamps_low(voltage):
    """At or below the lowest knot clamps to 0. The 0% knot is the
    low-battery shutdown at the ADC blind floor (ADR 0021), so a sane
    read below it can only be the last gasp before the debounce fires."""
    assert estimate_soc(voltage) == 0


@pytest.mark.unit
@pytest.mark.parametrize("voltage", [4.060, 4.20, 4.5, 5.0, 100.0])
def test_estimate_soc_clamps_high(voltage):
    """At or above the highest knot clamps to 100. The old 4.20 V top
    knot was unreachable under load; 100% is now the measured under-load
    voltage right after unplugging a charged unit."""
    assert estimate_soc(voltage) == 100


@pytest.mark.unit
@pytest.mark.parametrize(
    "chrg_code,expect_none",
    [
        (0b00, False),  # Not charging -> SoC estimated
        (0b01, True),  # Pre-charge   -> SoC None
        (0b10, True),  # Fast charging -> SoC None
        (0b11, False),  # Charge done  -> SoC estimated
    ],
)
def test_soc_none_while_charging(chrg_code, expect_none):
    """``state_of_charge_pct`` is None exactly while charging
    (Pre-charge / Fast Charging), where the terminal voltage is pulled
    up and a percentage would lie."""
    reg0b = chrg_code << 3
    state = decode_registers(reg0b, 0x49, 0x60, 0x9A, 0x00, 0.0)

    if expect_none:
        assert state.state_of_charge_pct is None
    else:
        assert isinstance(state.state_of_charge_pct, int)


@pytest.mark.unit
def test_estimate_soc_returns_int():
    """The estimate is always a plain int (UI consumers expect one)."""
    for v in (3.0, 3.42, 3.7, 3.99, 4.2):
        assert isinstance(estimate_soc(v), int)
