#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the main entry point for PiFinder it:
* Initializes the display
* Spawns keyboard process
* Sets up time/location via GPS
* Spawns camers/solver process
* then runs the UI loop

"""
import os
from time import sleep
from PIL import Image
from luma.core.interface.serial import spi
import numpy as np


def do_nothing():
    pass


def init_display():
    from luma.oled.device import ssd1351

    # init display  (SPI hardware)
    serial = spi(device=0, port=0)
    device_serial = ssd1351(serial, rotate=0, bgr=True)
    device_serial.capabilities(width=128, height=128, rotate=0, mode="RGB")
    device_serial.cleanup = do_nothing
    return device_serial


def show_splash():
    display = init_display()
    display.contrast(125)

    # load welcome image to screen
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    welcome_image_path = os.path.join(root_dir, "images", "welcome.png")
    welcome_image = Image.open(welcome_image_path)
    welcome_image = Image.fromarray(np.array(welcome_image)[:, :, ::-1])
    display.display(welcome_image.convert(display.mode))


if __name__ == "__main__":
    show_splash()
