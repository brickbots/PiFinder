#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Clear the screen for saving oled when developing
"""

from PIL import Image
from PiFinder import displays


def clear_screen():
    display = displays.get_display("ssd1351")
    display.set_brightness(125)
    screen = Image.new("RGB", display.resolution)

    display.device.display(screen.convert(display.device.mode))


if __name__ == "__main__":
    clear_screen()
