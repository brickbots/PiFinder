#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Startup hardware detection for rev-dependent optional hardware.

Builds a :class:`HardwareCapabilities` record once at startup (published
into ``SharedStateObj`` via ``set_hardware()``) that downstream code uses
as the single source of truth for "is this board a rev4 with the
BQ25895 charger?". The battery monitor only spawns when the charger is
detected.

Import-safe on dev machines: the I2C bus factory is imported under
try/except so this module loads even without blinka / an I2C bus.
"""

import logging
from pathlib import Path

from PiFinder.types.hardware import HardwareCapabilities

try:
    from PiFinder.i2c_bus import get_i2c
except (ImportError, NotImplementedError):
    get_i2c = None  # type: ignore[assignment]

logger = logging.getLogger("HardwareDetect")

# BQ25895 single-cell Li-ion charger, I2C address 0x6A.
BQ25895_ADDRESS = 0x6A

MODEL_FILE = Path("/proc/device-tree/model")


def is_compute_module(model_file: Path = MODEL_FILE) -> bool:
    """True on a Raspberry Pi Compute Module board.

    rev4 is the only PiFinder built on a Compute Module (CM4), so this marks
    rev4 without the charger, which does not answer while no battery is in.
    """
    try:
        model = model_file.read_bytes().rstrip(b"\x00").decode(errors="replace")
    except OSError:
        return False
    return model.startswith("Raspberry Pi Compute Module")


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

    ``is_rev4`` (display and buzzer) is true when the BQ25895 charger ACKs
    or the board is a Compute Module. The charger does not ACK without a
    battery, so the board model keeps a rev4 without a battery on the right
    display. The buzzer is a bare GPIO piezo (PWM ch0) that can't be probed
    directly, so ``has_buzzer`` follows ``is_rev4`` (see CONTEXT-MAP "Sound →
    system-wide").

    ``has_bq25895`` (battery monitor, battery icon) needs the charger to ACK.
    On a probe failure (no blinka, no I2C bus) it is False, and a dev machine
    or a rev3 board gets all-False capabilities.
    """
    compute_module = is_compute_module()
    try:
        present = i2c_present(BQ25895_ADDRESS)
    except Exception as e:
        logger.debug("Hardware detect: BQ25895 probe unavailable (%s)", e)
        present = False
    rev4 = present or compute_module
    return HardwareCapabilities(has_bq25895=present, has_buzzer=rev4, is_rev4=rev4)
