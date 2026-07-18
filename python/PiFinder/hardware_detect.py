#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Startup hardware detection for rev-dependent optional hardware.

Builds a :class:`HardwareCapabilities` record once at startup (published
into ``SharedStateObj`` via ``set_hardware()``) that downstream code uses
as the single source of truth for "is this board a rev-4 with the
BQ25895 charger?". The battery monitor only spawns when the charger is
detected.

Import-safe on dev machines: the I2C bus factory is imported under
try/except so this module loads even without blinka / an I2C bus.
"""

import logging

from PiFinder.types.hardware import HardwareCapabilities

try:
    from PiFinder.i2c_bus import get_i2c
except (ImportError, NotImplementedError):
    get_i2c = None  # type: ignore[assignment]

logger = logging.getLogger("HardwareDetect")

# BQ25895 single-cell Li-ion charger, I2C address 0x6A.
BQ25895_ADDRESS = 0x6A


def i2c_present(address: int) -> bool:
    """Non-destructive I2C presence check: does ``address`` ACK on the
    bus?

    ``scan()`` ACK-probes every address on the bus and returns those that
    responded — the primary presence signal for the BQ25895. (A stronger
    confirmation, reading REG14 and checking the part-number bits against
    ``battery_bq25895.EXPECTED_PN`` == ``0b111``, is available but the
    bare ACK is sufficient here.)

    Raises if no I2C bus is available (no blinka); callers that want a
    soft answer should catch.
    """
    if get_i2c is None:
        raise RuntimeError("blinka / board unavailable — no I2C bus")

    i2c = get_i2c()
    locked = False
    try:
        while not i2c.try_lock():
            pass
        locked = True
        return address in i2c.scan()
    finally:
        if locked:
            i2c.unlock()


def detect_capabilities() -> HardwareCapabilities:
    """Probe the board and return its :class:`HardwareCapabilities`.

    On any failure (no blinka, no I2C bus, probe error) returns all-False
    capabilities — a dev machine or a rev-3 board simply has no charger.

    ``has_buzzer`` is set from the **same** rev-4 charger probe: the buzzer is
    a bare GPIO piezo (PWM ch0) that can't be probed directly, so the BQ25895
    ACK is the rev-4 marker that implies both (see CONTEXT-MAP "Sound →
    system-wide").
    """
    try:
        present = i2c_present(BQ25895_ADDRESS)
        return HardwareCapabilities(has_bq25895=present, has_buzzer=present)
    except Exception as e:
        logger.debug("Hardware detect: BQ25895 probe unavailable (%s)", e)
        return HardwareCapabilities()
