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
from PiFinder.ui.base import UIModule
from PiFinder import obslog

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
        self.notes = {}
        self.target_index = None
        self.__catalog_names = {"N": "NGC", "I": " IC", "M": "Mes"}
        self._observing_session = None
        self.logged_time = 0
        super().__init__(*args)

    def record_object(self, _object, notes):
        """
        Creates a session if needed
        then records the current target

        _object should be a target like dict
        notes should be a dict

        These will be jsonified when logging
        """
        if self._observing_session == None:
            self._observing_session = obslog.Observation_session(self.shared_state)

        self._observing_session.log_object(
            catalog=_object["catalog"],
            designation=_object["designation"],
            solution=self.shared_state.solution(),
            notes=notes,
        )

    def key_c(self):
        """
        when Confirm is pressed,
        log it!
        """
        self.record_object(self.target, self.notes)

        # Start the timer for the confirm.
        self.logged_time = time.time()
        self.update(force=True)

    def key_d(self):
        """
        when D (don't) is pressed
        Exit back to chart
        """
        self.switch_to = "UIChart"

    def key_up(self):
        pass

    def key_down(self):
        pass

    def active(self):
        # Make sure we set the logged time to 0 to indicate we
        # have not logged yet
        self.logged_time = 0

        # Reset notes
        self.notes = {"Visibility": None, "Appeal": None}
        self.note_active = "Visibility"
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
        line = ""
        line += self.__catalog_names.get(self.target["catalog"], "UNK") + " "
        line += str(self.target["designation"])
        self.draw.text((0, 20), line, font=self.font_large, fill=RED)

        # ID Line in BOld
        # Type / Constellation
        object_type = OBJ_TYPES.get(self.target["obj_type"], self.target["obj_type"])
        object_text = f"{object_type: <14} {self.target['const']}"
        self.draw.text((0, 40), object_text, font=self.font_bold, fill=(0, 0, 128))

        # Rating/notes
        start_pos = 70
        i = 0
        for k, v in self.notes.items():
            text_color = (0, 0, 128)
            if k == self.note_active:
                text_color = RED
            line = f"{k: >10}: {str(v): <4}"
            self.draw.text(
                (0, start_pos + (i * 18)), line, font=self.font_bold, fill=text_color
            )
            i += 1

        # Bottom button help
        self.draw.rectangle([8, 112, 56, 128], fill=(0, 0, 32))
        self.draw.text((11, 111), "C", font=self.font_bold, fill=RED)
        self.draw.text((24, 111), "Log", font=self.font_bold, fill=(0, 0, 128))
        self.draw.rectangle([72, 112, 120, 128], fill=(0, 0, 32))
        self.draw.text((75, 111), "D", font=self.font_bold, fill=RED)
        self.draw.text((88, 111), "Exit", font=self.font_bold, fill=(0, 0, 128))

        return self.screen_update()

    def key_number(self, number):
        print(number)
