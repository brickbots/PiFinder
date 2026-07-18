#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Battery telemetry and fast-charge configuration for the rev4 PiFinder
board's TI BQ25895 single-cell Li-ion charger (I2C address 0x6A on bus 1).

Mostly telemetry: it reads battery voltage, charge status, power source
and a few diagnostics. The remaining writes are deliberate and narrow:

* pulsing REG02 ``CONV_START`` to trigger a one-shot ADC conversion (a
  telemetry trigger), and
* applying a fixed **fast-charge configuration** on each poll —
  disabling the I2C watchdog, disabling automatic USB adapter
  re-detection (REG02 ``AUTO_DPDM_EN``), and raising the input current
  limit and the fast-charge current to ~1.5 A. This is idempotent
  (writes only the registers that have drifted), so it both sets the
  config at power-up and re-asserts it after a chip reset or USB
  re-detection. It does NOT touch OTG/HIZ/charge-enable: OTG/boost stays
  disabled in hardware via the ``/OTG`` strap. See
  ``docs/adr/0017-battery-fast-charge-config.md`` (which supersedes
  ``0006``) and the glossary at ``docs/ax/battery/CONTEXT.md``.

Durability between software runs: clearing ``AUTO_DPDM_EN`` is what lets
the configured input limit survive a cable unplug/replug while the
PiFinder is powered off. The charger stays powered from the battery when
the system is off (the power-off latch only drops the SYS boost; see ADR
0007), so its registers persist — and with the watchdog disabled nothing
resets them. The one remaining trigger that would otherwise drop IINLIM
back to ~500 mA is the chip re-running USB adapter detection on the next
cable insertion; disabling ``AUTO_DPDM_EN`` removes it, so once the app
has configured the chip once, charging stays fast across later replugs
with no software running. (A full power-on reset — battery fully drained
or disconnected — reverts ``AUTO_DPDM_EN`` to its default, so the first
insertion after that charges slowly until the PiFinder is next booted.)

Register scaling below was verified against ``BQ25895-datasheet.pdf``
(TI SLUSC88C, the REGxx field-description tables) and cross-checked
against a live rev4 unit. The chip has **no fuel gauge**: battery
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

# I2C address of the BQ25895 (bus 1 on the rev4 board).
BQ25895_ADDRESS = 0x6A

# --- Register addresses (verified against the datasheet register map) ---
REG00 = 0x00  # input source: EN_HIZ [7], EN_ILIM [6], IINLIM [5:0]
REG02 = 0x02  # ADC/adapter ctrl: CONV_START [7], CONV_RATE [6], AUTO_DPDM_EN [0]
REG04 = 0x04  # charge current: EN_PUMPX [7], ICHG [6:0]
REG07 = 0x07  # timers/watchdog: EN_TERM [7], WATCHDOG [5:4], EN_TIMER [3]
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

# --- Fast-charge configuration (written at runtime; see ADR 0017) ---
# Targets are ~1.5 A. The chip quantises each field, so the achieved
# value is the nearest representable step (see the _encode_* helpers).
TARGET_INPUT_LIMIT_MA = 1500  # REG00 IINLIM (input current limit)
TARGET_CHARGE_CURRENT_MA = 1500  # REG04 ICHG (fast-charge current)

# Field scaling (datasheet REG00 / REG04 tables).
IINLIM_OFFSET_MA = 100  # IINLIM minimum / offset
IINLIM_STEP_MA = 50
ICHG_STEP_MA = 64  # ICHG has no offset

# Field masks for read-modify-write — every config write preserves the
# bits outside its field. In particular REG00 bit6 EN_ILIM is preserved,
# so the external ILIM-pin resistor stays a hardware ceiling on input
# current (effective limit = min(IINLIM, ILIM pin)); REG04 bit7 EN_PUMPX
# is preserved.
WATCHDOG_MASK = 0x30  # REG07[5:4]; writing 00 disables the I2C watchdog
AUTO_DPDM_MASK = 0x01  # REG02[0]; writing 0 disables auto USB adapter detection
IINLIM_MASK = 0x3F  # REG00[5:0]
ICHG_MASK = 0x7F  # REG04[6:0]


def _encode_iinlim(ma: int) -> int:
    """Encode an input current limit (mA) into the REG00 IINLIM field."""
    field = round((ma - IINLIM_OFFSET_MA) / IINLIM_STEP_MA)
    return max(0, min(IINLIM_MASK, field))


def _encode_ichg(ma: int) -> int:
    """Encode a fast-charge current (mA) into the REG04 ICHG field."""
    field = round(ma / ICHG_STEP_MA)
    return max(0, min(ICHG_MASK, field))


def plan_charging_writes(reg00: int, reg02: int, reg04: int, reg07: int):
    """Given the current REG00/02/04/07 bytes, return the ``[(reg, value),
    ...]`` writes needed to reach the fast-charge config, preserving the
    bits outside each field.

    PURE — no hardware; the main unit-test target for the config path.

    Returns only the registers whose value actually changes, so once the
    chip is configured it returns ``[]`` and the per-poll re-assert costs
    nothing. REG07 (watchdog) is emitted **first** so that disabling the
    watchdog precedes the other writes — otherwise a watchdog timeout
    mid-sequence could reset them back to defaults. The REG02 write clears
    only ``AUTO_DPDM_EN`` (bit 0), so it preserves ``CONV_START`` and the
    other adapter-detection bits; this is what makes the input limit
    survive a cable replug while powered off (see module docstring / ADR
    0017).
    """
    desired07 = reg07 & ~WATCHDOG_MASK
    desired02 = reg02 & ~AUTO_DPDM_MASK
    desired00 = (reg00 & ~IINLIM_MASK) | _encode_iinlim(TARGET_INPUT_LIMIT_MA)
    desired04 = (reg04 & ~ICHG_MASK) | _encode_ichg(TARGET_CHARGE_CURRENT_MA)

    writes = []
    if desired07 != reg07:
        writes.append((REG07, desired07))
    if desired02 != reg02:
        writes.append((REG02, desired02))
    if desired00 != reg00:
        writes.append((REG00, desired00))
    if desired04 != reg04:
        writes.append((REG04, desired04))
    return writes


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
# Percent means "fraction of typical-load runtime remaining", not capacity
# (see docs/adr/0020-soc-as-runtime-fraction.md). These knots are still the
# generic Li-ion placeholder; measured knots from bench discharge runs pend.
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

    Reads registers, triggers one-shot ADC conversions, and applies the
    fast-charge configuration (input/charge current limits + watchdog).
    It does not touch OTG/HIZ/charge-enable — OTG/boost stays disabled in
    hardware via the ``/OTG`` strap.
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

    def apply_charging_config(self) -> None:
        """Apply the fast-charge configuration (~1.5 A input limit and
        fast-charge current, I2C watchdog disabled, automatic USB adapter
        re-detection disabled), preserving unrelated bits in each register.

        Idempotent: reads REG00/02/04/07, computes the needed writes via
        :func:`plan_charging_writes`, and writes only what has drifted.
        In steady state this is four reads and no writes; after a chip
        reset or USB re-detection (which revert the registers to
        defaults) it re-applies the config. Called once per poll, so the
        config is set at power-up and continuously re-asserted.
        """
        reg00 = self.read_reg(REG00)
        reg02 = self.read_reg(REG02)
        reg04 = self.read_reg(REG04)
        reg07 = self.read_reg(REG07)
        for reg, value in plan_charging_writes(reg00, reg02, reg04, reg07):
            self.write_reg(reg, value)
            logger.info(
                "BQ25895: set REG%02X = 0x%02X (fast-charge config)", reg, value
            )

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
            # Re-assert the fast-charge config every poll: applies it at
            # power-up and restores it after a chip reset / USB
            # re-detection. Idempotent, so this is a no-op once set.
            chip.apply_charging_config()
        except Exception as e:
            # A failed config write must not stop telemetry.
            logger.warning("Battery: applying fast-charge config failed: %s", e)
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
