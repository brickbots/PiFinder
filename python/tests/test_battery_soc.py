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
        (3.18, 3),  # between (3.00, 0) and (3.30, 5): frac 0.6 -> 3%
        (3.61, 35),  # between (3.55, 25) and (3.70, 50): frac 0.4 -> 35%
        (3.76, 60),  # between (3.70, 50) and (3.85, 75): frac 0.4 -> 60%
    ],
)
def test_estimate_soc_interpolates(voltage, expected):
    assert estimate_soc(voltage) == expected


@pytest.mark.unit
@pytest.mark.parametrize("voltage", [2.5, 2.99, 0.0, -1.0])
def test_estimate_soc_clamps_low(voltage):
    """Below the lowest knot clamps to 0."""
    assert estimate_soc(voltage) == 0


@pytest.mark.unit
@pytest.mark.parametrize("voltage", [4.20, 4.5, 5.0, 100.0])
def test_estimate_soc_clamps_high(voltage):
    """At or above the highest knot clamps to 100."""
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
