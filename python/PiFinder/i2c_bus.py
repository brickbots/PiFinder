#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
I2C bus selection for PiFinder peripherals (BNO055 IMU, BQ25895 charger).

The BCM2835/BCM2711 hardware I2C block (Pi 4 and earlier) has a
well-documented silicon bug: when a slave stretches the clock — which the
BNO055 does on almost every transaction — the controller can emit a
too-short SCL pulse and corrupt the transfer. Boards affected by that bug
provision a software (bit-banged) i2c-gpio bus on the same SDA/SCL pins
via a device-tree overlay; i2c-gpio implements clock stretching per spec.

Which bus exists is a boot-configuration decision (the per-board NixOS
hardware profile). This module hands out whatever the device tree
provides: the i2c-gpio adapter when one is present, the default hardware
bus otherwise. Boards with a correct I2C controller (Pi 5 / CM5 with RP1)
simply don't provision the overlay and get the hardware bus.
"""

import glob
import logging

import board
from adafruit_extended_bus import ExtendedI2C

logger = logging.getLogger("I2C")


def _is_gpio_adapter(adapter_dir: str) -> bool:
    """Return True when the sysfs adapter dir belongs to an i2c-gpio bus.

    Checks the adapter name first, then the platform device's device-tree
    compatible string (the adapter dir's parent) — the name format has
    varied across kernel versions, the compatible string has not.
    """
    try:
        with open(adapter_dir + "/name") as handle:
            if handle.read().strip().startswith("i2c-gpio"):
                return True
    except OSError:
        pass
    try:
        with open(adapter_dir + "/../of_node/compatible", "rb") as handle:
            return b"i2c-gpio" in handle.read()
    except OSError:
        return False


def get_i2c():
    """Return the I2C bus object for PiFinder peripherals.

    Prefers a bit-banged i2c-gpio adapter when the device tree provides
    one; falls back to the default hardware bus (``board.I2C()``).
    """
    for name_path in sorted(glob.glob("/sys/bus/i2c/devices/i2c-*/name")):
        adapter_dir = name_path.rsplit("/", 1)[0]
        if _is_gpio_adapter(adapter_dir):
            bus_number = int(adapter_dir.rsplit("/i2c-", 1)[1])
            logger.info("Using i2c-gpio bus /dev/i2c-%d", bus_number)
            return ExtendedI2C(bus_number)
    logger.info("Using default hardware I2C bus")
    return board.I2C()
