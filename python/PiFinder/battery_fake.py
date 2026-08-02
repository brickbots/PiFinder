#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Fake battery monitor — the ``-fh`` (fake-hardware) twin of
``battery_bq25895``.

Emits a deterministic, slowly-discharging :class:`BatteryState` so the
rest of the system can be exercised without a real BQ25895. While
discharging it reports running from the battery
(``on_external_power=False``, ``charge_status=NOT_CHARGING``), so state
of charge is estimated via the same LUT as the real driver.

Each sweep ends the way a real discharge does (ADR 0021): after the
voltage reaches the bottom of the sweep the fake goes **ADC-blind**
(``battery_voltage=None``) for a few polls — enough to trip the
low-battery shutdown debounce — then shows a brief **charging** phase
(which re-arms the warner's once-per-discharge warning latches) and
wraps back to full for the next lap. A dev run with ``-fh -fb``
therefore crosses the 10%/5% warnings and the blind-floor shutdown
warning within a few minutes, end to end — on every lap.
The main loop shows the shutdown warning but skips the actual OS
power-off on the Fake hardware platform, so a lap never powers off the
host (which may be a real Pi running ``-fh`` for docs screenshots).

Reuses the pure pieces (``estimate_soc``, ``LowBatteryShutdownTrigger``,
``POLL_INTERVAL``, ``BatteryState``) from ``battery_bq25895`` so fake
and real stay consistent.
"""

import logging
import time

from PiFinder.battery_bq25895 import (
    LOW_BATTERY_SHUTDOWN_POLLS,
    POLL_INTERVAL,
    LowBatteryShutdownTrigger,
    estimate_soc,
)
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.types.hardware import BatteryState, ChargeStatus

logger = logging.getLogger("Battery.fake")

# Discharge sweep bounds (volts) and per-poll decrement. The bounds track
# the measured discharge curve: full is the 100% knot, empty sits just
# above the ADC blind floor. When the sweep reaches the low bound the
# fake goes blind for FAKE_BLIND_POLLS polls (below), then wraps back to
# full, so the value keeps moving for as long as the process runs.
FAKE_VOLTAGE_FULL = 4.06
FAKE_VOLTAGE_EMPTY = 3.54
FAKE_VOLTAGE_STEP = 0.02

# Blind polls per lap: enough consecutive raw-0 "reads" to trip the
# shutdown debounce, plus margin so the blind state is visible in the UI.
FAKE_BLIND_POLLS = LOW_BATTERY_SHUTDOWN_POLLS + 2

# Charging polls between laps: the warner's thresholds latch for a whole
# discharge and re-arm only on external power, so each lap ends with a
# brief fake "recharge" — otherwise the 10%/5% warnings would fire on the
# first lap only and every later lap would run silent.
FAKE_CHARGING_POLLS = 2


def battery_monitor(shared_state, console_queue, ui_queue, log_queue):
    """Process entry mirroring ``battery_bq25895.battery_monitor``."""
    MultiprocLogging.configurer(log_queue)
    logger.debug("Starting fake battery monitor")

    shutdown_trigger = LowBatteryShutdownTrigger()
    voltage = FAKE_VOLTAGE_FULL
    blind_polls_left = 0
    charging_polls_left = 0
    while True:
        if blind_polls_left > 0:
            # ADC-blind tail: what the real decoder publishes below the
            # blind floor — no ADC-derived values, status still valid.
            state = BatteryState(
                battery_voltage=None,
                charge_status=ChargeStatus.NOT_CHARGING,
                on_external_power=False,
                state_of_charge_pct=None,
                charge_current_ma=None,
                vbus_voltage=None,
                sys_voltage=None,
                timestamp=time.time(),
            )
            blind_polls_left -= 1
            if blind_polls_left == 0:
                charging_polls_left = FAKE_CHARGING_POLLS
                voltage = FAKE_VOLTAGE_FULL
        elif charging_polls_left > 0:
            # Between-laps "recharge": on external power with SoC None
            # (never estimated while charging), which re-arms the
            # warner's latched thresholds for the next lap.
            state = BatteryState(
                battery_voltage=FAKE_VOLTAGE_FULL,
                charge_status=ChargeStatus.FAST_CHARGING,
                on_external_power=True,
                state_of_charge_pct=None,
                charge_current_ma=1500.0,
                vbus_voltage=5.1,
                sys_voltage=FAKE_VOLTAGE_FULL,
                timestamp=time.time(),
            )
            charging_polls_left -= 1
        else:
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
            voltage -= FAKE_VOLTAGE_STEP
            if voltage < FAKE_VOLTAGE_EMPTY:
                blind_polls_left = FAKE_BLIND_POLLS

        if shared_state is not None:
            shared_state.set_battery(state)
        if shutdown_trigger.update(state.adc_blind, state.on_external_power):
            logger.warning(
                "Battery (fake): sustained blind reads — "
                "requesting low-battery shutdown"
            )
            ui_queue.put("low_battery_shutdown")
        time.sleep(POLL_INTERVAL)
