#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Read-only battery telemetry for the rev-4 PiFinder board's TI BQ25895
single-cell Li-ion charger (I2C address 0x6A on bus 1).

This is **read-only telemetry** — it never configures the power path
(no OTG/HIZ/current-limit/charge-enable writes). The *only* write it
makes is pulsing REG02 ``CONV_START`` to trigger a one-shot ADC
conversion, which is a telemetry trigger, not power-path control. See
``docs/adr/0006-battery-read-only-telemetry.md`` and the glossary at
``docs/ax/battery/CONTEXT.md``.

Register scaling below was verified against ``BQ25895-datasheet.pdf``
(TI SLUSC88C, the REGxx field-description tables) and cross-checked
against a live rev-4 unit. The chip has **no fuel gauge**: battery
voltage is the only measured quantity; state of charge is an estimate.

Structure note: ``decode_registers`` and ``estimate_soc`` are PURE (no
hardware) so the bulk of the logic is unit-testable without a board.
``board`` is imported lazily-guarded so this module — and the pure
pieces ``battery_fake`` reuses — imports cleanly on dev machines.
"""

import logging
import time

from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.types.hardware import BatteryState, ChargeStatus

try:
    import board
    from adafruit_bus_device.i2c_device import I2CDevice
except (ImportError, NotImplementedError):
    # No blinka / not on real hardware: the pure decode helpers and module
    # constants still import. The BQ25895 class raises on construction.
    board = None
    I2CDevice = None

logger = logging.getLogger("Battery.bq25895")

# I2C address of the BQ25895 (bus 1 on the rev-4 board).
BQ25895_ADDRESS = 0x6A

# --- Register addresses (verified against the datasheet register map) ---
REG02 = 0x02  # ADC control: CONV_START [7], CONV_RATE [6]
REG0B = 0x0B  # status: VBUS_STAT [7:5], CHRG_STAT [4:3], PG_STAT [2], VSYS_STAT [0]
REG0E = 0x0E  # BATV [6:0] (bit7 THERM_STAT) — battery voltage
REG0F = 0x0F  # SYSV [6:0] — system voltage
REG11 = 0x11  # VBUSV [6:0] (bit7 VBUS_GD) — VBUS voltage
REG12 = 0x12  # ICHGR [6:0] — charge current
REG14 = 0x14  # PN [5:3] part number (0b111 == BQ25895)

# REG02 ADC one-shot trigger. Set bit7 via read-modify-write; it
# self-clears when the conversion completes. Bit6 (CONV_RATE) stays 0
# so the conversion is one-shot, not continuous.
CONV_START_MASK = 0x80

# REG14 expected part-number value (PN[5:3]) for the BQ25895.
EXPECTED_PN = 0b111

# --- ADC scaling (datasheet REGxx field tables; verified on hardware) ---
BATV_OFFSET_V = 2.304
BATV_STEP_V = 0.020
SYSV_OFFSET_V = 2.304
SYSV_STEP_V = 0.020
VBUSV_OFFSET_V = 2.6
VBUSV_STEP_V = 0.100
ICHGR_STEP_MA = 50.0

# Poll cadence. Battery is slow-moving; the one-shot conversion adds only
# tens of ms. Module constant so it is easy to retune.
POLL_INTERVAL = 5.0
# How long to wait for CONV_START to self-clear before giving up.
CONV_TIMEOUT = 2.0
# How often to re-read REG02 while waiting for the conversion to finish.
CONV_POLL_INTERVAL = 0.01

# Piecewise-linear state-of-charge curve: (battery_voltage_V, percent).
# A coarse Li-ion estimate, tunable later with real PiFinder-load data.
SOC_LUT = [
    (3.00, 0),
    (3.30, 5),
    (3.55, 25),
    (3.70, 50),
    (3.85, 75),
    (4.20, 100),
]


def estimate_soc(voltage: float) -> int:
    """Estimate state of charge (0-100%) from battery voltage by
    interpolating the :data:`SOC_LUT` knots, clamped to 0-100.

    This is a rough estimate off a discharge curve, not a measured value
    (the chip has no fuel gauge). Callers treat it as UI-only and never
    use it while charging.
    """
    if voltage <= SOC_LUT[0][0]:
        return SOC_LUT[0][1]
    if voltage >= SOC_LUT[-1][0]:
        return SOC_LUT[-1][1]
    for (v_lo, pct_lo), (v_hi, pct_hi) in zip(SOC_LUT, SOC_LUT[1:]):
        if voltage <= v_hi:
            frac = (voltage - v_lo) / (v_hi - v_lo)
            pct = pct_lo + frac * (pct_hi - pct_lo)
            return max(0, min(100, int(round(pct))))
    return SOC_LUT[-1][1]  # unreachable: voltage is within the LUT range


def decode_registers(
    reg0b: int,
    reg0e: int,
    reg0f: int,
    reg11: int,
    reg12: int,
    timestamp: float,
) -> BatteryState:
    """Decode raw BQ25895 register bytes into a :class:`BatteryState`.

    PURE — no hardware access. This is the main unit-test target.

    State of charge is ``None`` while charging (Pre-charge / Fast
    Charging): the charger pulls the terminal voltage up, so a
    percentage would lie. Otherwise it is estimated from battery voltage.
    """
    charge_status = ChargeStatus((reg0b >> 3) & 0x03)
    on_external_power = bool((reg0b >> 2) & 0x01)

    battery_voltage = BATV_OFFSET_V + (reg0e & 0x7F) * BATV_STEP_V
    sys_voltage = SYSV_OFFSET_V + (reg0f & 0x7F) * SYSV_STEP_V
    vbus_voltage = VBUSV_OFFSET_V + (reg11 & 0x7F) * VBUSV_STEP_V
    charge_current_ma = (reg12 & 0x7F) * ICHGR_STEP_MA

    if charge_status in (ChargeStatus.PRE_CHARGE, ChargeStatus.FAST_CHARGING):
        state_of_charge_pct = None
    else:
        state_of_charge_pct = estimate_soc(battery_voltage)

    return BatteryState(
        battery_voltage=battery_voltage,
        charge_status=charge_status,
        on_external_power=on_external_power,
        state_of_charge_pct=state_of_charge_pct,
        charge_current_ma=charge_current_ma,
        vbus_voltage=vbus_voltage,
        sys_voltage=sys_voltage,
        timestamp=timestamp,
    )


class BQ25895:
    """Thin I2C wrapper around the BQ25895 charger.

    Reads registers and triggers one-shot ADC conversions. Makes no
    power-path writes (the one write is the conversion trigger).
    """

    def __init__(self, address: int = BQ25895_ADDRESS, i2c=None):
        if board is None or I2CDevice is None:
            raise RuntimeError("blinka / board unavailable — no I2C bus")
        if i2c is None:
            i2c = board.I2C()
        self._device = I2CDevice(i2c, address)

    def read_reg(self, reg: int) -> int:
        """Read a single 8-bit register."""
        buf = bytearray(1)
        with self._device as dev:
            dev.write_then_readinto(bytes([reg]), buf)
        return buf[0]

    def write_reg(self, reg: int, value: int) -> None:
        """Write a single 8-bit register."""
        with self._device as dev:
            dev.write(bytes([reg, value & 0xFF]))

    def start_conversion(self) -> bool:
        """Trigger a one-shot ADC conversion and wait for it to finish.

        Read-modify-write REG02 to set ``CONV_START`` without disturbing
        ``BOOST_FREQ`` / ``ICO_EN`` / ``CONV_RATE``. The bit self-clears
        when the conversion completes. Returns True on completion, False
        on timeout.
        """
        reg02 = self.read_reg(REG02)
        self.write_reg(REG02, reg02 | CONV_START_MASK)

        deadline = time.time() + CONV_TIMEOUT
        while time.time() < deadline:
            if not (self.read_reg(REG02) & CONV_START_MASK):
                return True
            time.sleep(CONV_POLL_INTERVAL)
        logger.warning(
            "BQ25895: ADC conversion did not complete within %.1fs", CONV_TIMEOUT
        )
        return False

    def read_state(self) -> BatteryState:
        """Trigger a fresh conversion, read the telemetry registers and
        decode them into a :class:`BatteryState`."""
        self.start_conversion()
        reg0b = self.read_reg(REG0B)
        reg0e = self.read_reg(REG0E)
        reg0f = self.read_reg(REG0F)
        reg11 = self.read_reg(REG11)
        reg12 = self.read_reg(REG12)
        return decode_registers(reg0b, reg0e, reg0f, reg11, reg12, time.time())


def battery_monitor(shared_state, console_queue, log_queue):
    """Process entry: poll the BQ25895 and publish into shared state.

    Mirrors ``imu_monitor``. On construction failure, log and exit — do
    NOT fall back to a fake reading. A fabricated battery value on real
    hardware would mislead; ``shared_state.battery()`` simply stays
    ``None`` (see CONTEXT.md "BatteryState is None vs 0%").
    """
    MultiprocLogging.configurer(log_queue)
    logger.debug("Starting battery monitor")

    try:
        chip = BQ25895()
    except Exception as e:
        logger.error("Battery: could not initialise BQ25895: %s", e)
        console_queue.put("Battery: BQ25895 init failed, monitor disabled")
        return

    while True:
        try:
            state = chip.read_state()
            if shared_state is not None:
                shared_state.set_battery(state)
        except Exception as e:
            # Transient I2C errors: log and keep polling.
            logger.warning("Battery: read failed: %s", e)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    logger.info("Reading BQ25895 battery state")
    try:
        _chip = BQ25895()
        for _ in range(5):
            print(_chip.read_state())
            time.sleep(POLL_INTERVAL)
    except Exception:
        logger.exception("Error reading BQ25895")
