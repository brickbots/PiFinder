"""
Unit tests for REG0B decode: charge status and power source.

Charge status (the charger's CHRG_STAT phase) and power source
(``on_external_power`` from PG_STAT) are separate facts — a unit can be
on external power with a full cell and not be charging.
"""

import pytest

from PiFinder.battery_bq25895 import decode_registers
from PiFinder.types.hardware import ChargeStatus


@pytest.mark.unit
@pytest.mark.parametrize(
    "chrg_code,expected",
    [
        (0b00, ChargeStatus.NOT_CHARGING),
        (0b01, ChargeStatus.PRE_CHARGE),
        (0b10, ChargeStatus.FAST_CHARGING),
        (0b11, ChargeStatus.CHARGE_DONE),
    ],
)
def test_charge_status_decode(chrg_code, expected):
    """All four CHRG_STAT codes (REG0B [4:3]) map to the right phase.

    Surrounding bits (VBUS_STAT [7:5], PG_STAT [2], VSYS_STAT [0]) are
    set to noise to confirm they don't leak into CHRG_STAT.
    """
    reg0b = (0b101 << 5) | (chrg_code << 3) | 0b1
    state = decode_registers(reg0b, 0x49, 0x60, 0x9A, 0x00, 0.0)
    assert state.charge_status is expected


@pytest.mark.unit
@pytest.mark.parametrize("pg_stat,expected", [(0, False), (1, True)])
def test_on_external_power_tracks_pg_stat(pg_stat, expected):
    """``on_external_power`` follows PG_STAT (REG0B bit 2), independent of
    charge status."""
    reg0b = pg_stat << 2
    state = decode_registers(reg0b, 0x49, 0x60, 0x9A, 0x00, 0.0)
    assert state.on_external_power is expected


@pytest.mark.unit
def test_external_power_independent_of_charge_status():
    """On external power but charge complete: power good, not charging."""
    # CHRG_STAT=11 (done), PG_STAT=1
    reg0b = (0b11 << 3) | (1 << 2)
    state = decode_registers(reg0b, 0x5E, 0x60, 0x9A, 0x00, 0.0)
    assert state.charge_status is ChargeStatus.CHARGE_DONE
    assert state.on_external_power is True
