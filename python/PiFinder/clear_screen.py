#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module simply turns of the screen

"""
import os
from luma.core.interface.serial import spi


def init_display():
    from luma.oled.device import ssd1351

    # init display  (SPI hardware)
    serial = spi(device=0, port=0)
    device_serial = ssd1351(serial, rotate=0, bgr=True)
    device_serial.capabilities(width=128, height=128, rotate=0, mode="RGB")
    return device_serial


def clear_screen():
    display = init_display()
    display.contrast(0)


if __name__ == "__main__":
    clear_screen()
