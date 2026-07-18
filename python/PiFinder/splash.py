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
from PIL import Image, ImageDraw
from PiFinder import displays
from PiFinder import hardware_detect
import numpy as np


def do_nothing():
    pass


def show_splash():
    # Drive whichever panel the main app will: rev4 boards use the 176x176
    # SSD1333, everything else the 128x128 SSD1351. This mirrors main.py's
    # hardware_detect-based selection so the boot splash matches the running UI
    # (and doesn't init the wrong controller). detect_capabilities() is
    # import-safe and never raises -- a dev box / rev3 board falls back to the
    # SSD1351.
    capabilities = hardware_detect.detect_capabilities()
    display_hardware = "ssd1333" if capabilities.has_bq25895 else "ssd1351"
    display = displays.get_display(display_hardware)
    display.device.cleanup = do_nothing
    display.set_brightness(125)

    # load welcome image and scale it to fill whichever panel we're on. The
    # asset is authored at 128x128; both panels are square so it scales without
    # distortion (a no-op on the 128 panel).
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    welcome_image_path = os.path.join(root_dir, "images", "welcome.png")
    welcome_image = Image.open(welcome_image_path)
    welcome_image = Image.fromarray(np.array(welcome_image)[:, :, ::-1])
    if welcome_image.size != (display.resX, display.resY):
        welcome_image = welcome_image.resize((display.resX, display.resY))
    screen_draw = ImageDraw.Draw(welcome_image)

    # Display version and Wifi mode in a top banner spanning the panel width
    with open(os.path.join(root_dir, "version.txt"), "r") as ver_f:
        version = "v" + ver_f.read()

    with open(os.path.join(root_dir, "wifi_status.txt"), "r") as wifi_f:
        wifi_mode = wifi_f.read()
    banner_height = round(display.resY * 16 / 128)
    screen_draw.rectangle([0, 0, display.resX, banner_height], fill=(0, 0, 0))
    screen_draw.text(
        (0, 1),
        f"Wifi:{wifi_mode: <6}  {version: >8}",
        font=display.fonts.base.font,
        fill=(255, 0, 0),
    )

    display.device.display(welcome_image.convert(display.device.mode))


if __name__ == "__main__":
    show_splash()
