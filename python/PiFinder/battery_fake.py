#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Fake battery monitor — the ``-fh`` (fake-hardware) twin of
``battery_bq25895``.

Emits a deterministic, slowly-discharging :class:`BatteryState` so the
rest of the system can be exercised without a real BQ25895. It always
reports running from the battery (``on_external_power=False``,
``charge_status=NOT_CHARGING``), so state of charge is always estimated
via the same LUT as the real driver.

Reuses the pure pieces (``estimate_soc``, ``POLL_INTERVAL``,
``BatteryState``) from ``battery_bq25895`` so fake and real stay
consistent.
"""

import logging
import time

from PiFinder.battery_bq25895 import POLL_INTERVAL, estimate_soc
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.types.hardware import BatteryState, ChargeStatus

logger = logging.getLogger("Battery.fake")

# Discharge sweep bounds (volts) and per-poll decrement. When the fake
# cell reaches the low bound it wraps back to full, so the value keeps
# moving for as long as the process runs.
FAKE_VOLTAGE_FULL = 4.0
FAKE_VOLTAGE_EMPTY = 3.0
FAKE_VOLTAGE_STEP = 0.02


def battery_monitor(shared_state, console_queue, log_queue):
    """Process entry mirroring ``battery_bq25895.battery_monitor``."""
    MultiprocLogging.configurer(log_queue)
    logger.debug("Starting fake battery monitor")

    # BRANCH-ONLY (battery-runtime-test): same telemetry path as the real
    # monitor so the whole pipeline is dev-testable with -fh -fb.
    telemetry = None
    try:
        from PiFinder.battery_telemetry import TelemetryLogger

        telemetry = TelemetryLogger(shared_state, "fake")
        console_queue.put("BATTERY RUNTIME TEST: logging (fake)")
    except Exception as e:
        logger.error("Battery telemetry init failed: %s", e)

    voltage = FAKE_VOLTAGE_FULL
    while True:
        state = BatteryState(
            battery_voltage=voltage,
            charge_status=ChargeStatus.NOT_CHARGING,
            on_external_power=False,
            state_of_charge_pct=estimate_soc(voltage),
            charge_current_ma=0.0,
            vbus_voltage=0.0,
            sys_voltage=voltage,
            timestamp=time.time(),
        )
        if shared_state is not None:
            shared_state.set_battery(state)
        if telemetry is not None:
            telemetry.log(state, estimate_soc(voltage))

        voltage -= FAKE_VOLTAGE_STEP
        if voltage < FAKE_VOLTAGE_EMPTY:
            voltage = FAKE_VOLTAGE_FULL
        time.sleep(POLL_INTERVAL)
