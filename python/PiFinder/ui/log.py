#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import datetime
import time
import os
import uuid
import sqlite3
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps

from PiFinder import solver
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.image_util import gamma_correct_low, subtract_background, red_image
from PiFinder import plot
from PiFinder.ui.base import UIModule

RED = (0, 0, 255)


class UILog(UIModule):
    """
    Log an observation of the
    current target

    """

    __title__ = "LOG"

    def __init__(self, *args):
        self.target = None
        self.target_list = []
        self.target_index = None
        self.object_text = ["No Object Found"]
        self.__catalog_names = {"N": "NGC", "I": " IC", "M": "Mes"}
        super().__init__(*args)

    def key_enter(self):
        """
        when enter is pressed,
        log it!
        """
        pass

    def key_up(self):
        pass

    def key_down(self):
        pass

    def active(self):
        state_target = self.shared_state.target()
        if state_target != self.target:
            self.target = state_target
        self.update()

    def update(self):
        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))

        if not self.target:
            self.draw.text((0, 20), "No Target Set", font=self.font_large, fill=RED)
            return self.screen_update()

        # Target Name
        line = "Log "
        line += self.__catalog_names.get(self.target["catalog"], "UNK") + " "
        line += str(self.target["designation"])
        self.draw.text((0, 20), line, font=self.font_large, fill=RED)

        # ID Line in BOld
        self.draw.text((0, 40), self.object_text[0], font=self.font_bold, fill=RED)

        return self.screen_update()
