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
from PiFinder.displays import DisplayBase, get_display
from PiFinder.ui import marking_menus


if __name__ == "__main__":
    display = get_display("pg_128")

    _tmp = marking_menus.render_menu_item("Tester", display.fonts.bold, display.colors.get(128), display.resolution, 110, 0)


    display.device.display(_tmp.convert(display.device.mode))
    sleep(1)
    display.device.display(_tmp.convert(display.device.mode))



