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
from PIL import Image, ImageDraw
from luma.core.interface.serial import spi
import numpy as np
from PiFinder.ui.fonts import Fonts as fonts


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
    screen_draw = ImageDraw.Draw(welcome_image)

    # Display version and Wifi mode
    with open(os.path.join(root_dir, "version.txt"), "r") as ver_f:
        version = "v" + ver_f.read()

    with open(os.path.join(root_dir, "wifi_status.txt"), "r") as wifi_f:
        wifi_mode = wifi_f.read()
    screen_draw.rectangle([0, 0, 128, 16], fill=(0, 0, 0))
    screen_draw.text(
        (0, 1),
        f"Wifi:{wifi_mode: <6}  {version: >8}",
        font=fonts.base,
        fill=(255, 0, 0),
    )

    display.display(welcome_image.convert(display.mode))


if __name__ == "__main__":
    show_splash()
