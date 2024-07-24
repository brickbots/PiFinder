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
from PiFinder.displays import get_display
from PiFinder.ui import marking_menus
import numpy as np
from PiFinder.utils import Timer


def do_nothing():
    pass


if __name__ == "__main__":
    display = get_display("ssd1351")

    # load welcome image to screen
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    welcome_image_path = os.path.join(root_dir, "images", "welcome.png")
    welcome_image = Image.open(welcome_image_path)
    welcome_image = Image.fromarray(np.array(welcome_image)[:, :, ::-1])

    menu_items = [
        marking_menus.MarkingMenuOption(label="OPTION0"),
        marking_menus.MarkingMenuOption(label="OPTION1", selected=True),
        marking_menus.MarkingMenuOption(label="OPTION2"),
        marking_menus.MarkingMenuOption(label="OPTION3"),
    ]

    with Timer("MM") as m:
        _tmp = marking_menus.render_marking_menu(welcome_image, menu_items, display, 40)

    display.device.display(_tmp.convert(display.device.mode))
    sleep(10)
