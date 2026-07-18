"""
Unit tests for the pure BQ25895 register decode.

Register byte values and the expected scaling are cross-checked against
``BQ25895-datasheet.pdf`` (TI SLUSC88C) and the live rev-4 readings noted
in the battery handoff. No hardware is touched — ``decode_registers`` is
a pure function.
"""

import pytest

from PiFinder.battery_bq25895 import decode_registers
from PiFinder.types.hardware import ChargeStatus


@pytest.mark.unit
def test_decode_not_charging_on_external_power():
    """A full-ish cell sitting on external power, not charging.

    Register bytes:
      REG0B 0x04 -> CHRG_STAT=00 (not charging), PG_STAT=1 (power good)
      REG0E 0x49 -> BATV 73  -> 2.304 + 73*0.020 = 3.764 V
      REG0F 0x60 -> SYSV 96  -> 2.304 + 96*0.020 = 4.224 V
      REG11 0x9A -> VBUS_GD=1, VBUSV 26 -> 2.6 + 26*0.100 = 5.2 V
      REG12 0x00 -> 0 mA
    """
    state = decode_registers(
        reg0b=0x04,
        reg0e=0x49,
        reg0f=0x60,
        reg11=0x9A,
        reg12=0x00,
        timestamp=123.0,
    )

    assert state.battery_voltage == pytest.approx(3.764)
    assert state.sys_voltage == pytest.approx(4.224)
    assert state.vbus_voltage == pytest.approx(5.2)
    assert state.charge_current_ma == pytest.approx(0.0)
    assert state.charge_status is ChargeStatus.NOT_CHARGING
    assert state.on_external_power is True
    assert state.adc_blind is False
    # 3.764 V interpolates between (3.736, 25) and (3.834, 50) -> ~32.1 -> 32
    assert state.state_of_charge_pct == 32
    assert state.timestamp == 123.0


@pytest.mark.unit
def test_decode_fast_charging_full_cell():
    """A fast-charging cell. SoC is undefined (None) while charging.

    Register bytes:
      REG0B 0x14 -> CHRG_STAT=10 (fast charging), PG_STAT=1
      REG0E 0x5E -> BATV 94 -> 2.304 + 94*0.020 = 4.184 V (live full 1S)
      REG12 0x20 -> ICHGR 32 -> 32*50 = 1600 mA
    """
    state = decode_registers(
        reg0b=0x14,
        reg0e=0x5E,
        reg0f=0x5E,
        reg11=0x9A,
        reg12=0x20,
        timestamp=0.0,
    )

    assert state.battery_voltage == pytest.approx(4.184)
    assert state.charge_status is ChargeStatus.FAST_CHARGING
    assert state.on_external_power is True
    assert state.charge_current_ma == pytest.approx(1600.0)
    # No state of charge while charging.
    assert state.state_of_charge_pct is None


@pytest.mark.unit
def test_decode_masks_high_bits():
    """THERM_STAT (REG0E bit7) and VBUS_GD (REG11 bit7) must not leak
    into the decoded voltages — only bits [6:0] scale."""
    # 0xC9 == 0x49 with THERM_STAT set; voltage must be unchanged.
    with_therm = decode_registers(0x00, 0xC9, 0x60, 0x9A, 0x00, 0.0)
    without_therm = decode_registers(0x00, 0x49, 0x60, 0x9A, 0x00, 0.0)
    assert with_therm.battery_voltage == without_therm.battery_voltage
    assert with_therm.battery_voltage == pytest.approx(3.764)

    # 0x9A has VBUS_GD set; 0x1A is the same VBUSV without it.
    gd = decode_registers(0x00, 0x49, 0x60, 0x9A, 0x00, 0.0)
    no_gd = decode_registers(0x00, 0x49, 0x60, 0x1A, 0x00, 0.0)
    assert gd.vbus_voltage == no_gd.vbus_voltage == pytest.approx(5.2)


@pytest.mark.unit
def test_decode_raw_zero_batv_is_blind_not_a_measurement():
    """A raw-0 BATV read is an ADC-blind poll (battery below the ~3.5 V
    blind floor), NOT a 2.304 V measurement: every ADC-derived field is
    ``None`` so the decode artifact can never reach the discharge curve
    or any consumer (ADR 0021)."""
    state = decode_registers(0x00, 0x00, 0x00, 0x00, 0x00, 0.0)
    assert state.adc_blind is True
    assert state.battery_voltage is None
    assert state.sys_voltage is None
    assert state.vbus_voltage is None
    assert state.charge_current_ma is None
    assert state.state_of_charge_pct is None
    # Status bits are plain register reads, not conversions — still decoded.
    assert state.charge_status is ChargeStatus.NOT_CHARGING
    assert state.on_external_power is False


@pytest.mark.unit
def test_decode_blind_with_therm_stat_set():
    """THERM_STAT (REG0E bit7) does not count as battery-voltage bits:
    0x80 is still a raw-0 BATV field, hence blind."""
    state = decode_registers(0x00, 0x80, 0x00, 0x00, 0x00, 0.0)
    assert state.adc_blind is True
    assert state.battery_voltage is None


@pytest.mark.unit
def test_decode_blind_on_charger_keeps_status():
    """Deeply discharged cell on a charger: BATV raw 0 (blind) while the
    status bits keep working below the floor. Power source and charge
    phase must stay trustworthy — they gate the shutdown trigger, which
    must never fire on external power.

    REG0B 0x0C -> CHRG_STAT=01 (pre-charge), PG_STAT=1 (power good).
    """
    state = decode_registers(0x0C, 0x00, 0x00, 0x9A, 0x00, 0.0)
    assert state.adc_blind is True
    assert state.battery_voltage is None
    assert state.state_of_charge_pct is None
    assert state.charge_status is ChargeStatus.PRE_CHARGE
    assert state.on_external_power is True
