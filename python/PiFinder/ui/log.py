#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import datetime
import time
from PIL import  ImageFont

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
        self.modal_timer = 0
        self.modal_duration = 0
        self.modal_text = None
        self.font_small = ImageFont.truetype(
            "/usr/share/fonts/truetype/Roboto_Mono/static/RobotoMono-Bold.ttf", 8
        )
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

        return self._observing_session.log_object(
            catalog=_object["catalog"],
            designation=_object["designation"],
            solution=self.shared_state.solution(),
            notes=notes,
        )

    def key_number(self, number):
        """
            A number key should
            rate that attribute
            and move on to the next
            potential note
        """
        self.notes[self.note_active] = number

        # Move to next active note...
        note_items = list(self.notes.keys())
        current_index = note_items.index(self.note_active)
        current_index += 1
        if current_index >= len(note_items):
            current_index = 0
        self.note_active=note_items[current_index]


    def key_b(self):
        """
        when B is pressed,
        Just log it!
        """
        self.record_object(self.target, self.notes)

        # Start the timer for the confirm.
        self.modal_timer = time.time()
        self.modal_duration = 2
        self.modal_text = "Logged!"
        self.update()

    def key_c(self):
        """
        when c is pressed,
        photo and log it!
        """
        session_uid, obs_id = self.record_object(self.target, self.notes)

        # Start the timer for the confirm.
        self.modal_timer = time.time()
        self.modal_duration = 2
        self.modal_text = "Taking Photo"
        filename = f"{session_uid}_{obs_id}"
        self.command_queues["camera"].put("save_hi:" + filename)
        self.update()
        wait = True
        while wait:
            # we need to wait until we have another solve image
            # check every 2 seconds...
            sleep(.2)
            self.shared_state.last_image_time() > self.modal_timer + 1:
                wait = False
                self.modal_timer = time.time()
                self.modal_duration = 1
                self.modal_text = "Logged!"


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

    def update(self, force=False):
        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))

        if self.modal_text:
            if time.time() - self.modal_timer > self.modal_duration:
                self.switch_to = "UIChart"
                return self.screen_update()

            padded_text = (" " * int((14 - len(self.modal_text)) / 2)) + self.modal_text

            self.draw.text((0, 50), padded_text, font=self.font_large, fill=RED)
            return self.screen_update()


        if not self.shared_state.solve_state():
            self.draw.text((0, 20), "No Solve Yet", font=self.font_large, fill=RED)
            return self.screen_update()


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
        self.draw.rectangle([0, 118, 40, 128], fill=(0, 0, 32))
        self.draw.text((2, 117), "B", font=self.font_small, fill=RED)
        self.draw.text((10, 117), "Log", font=self.font_small, fill=(0, 0, 128))
        self.draw.rectangle([44, 118, 84, 128], fill=(0, 0, 32))
        self.draw.text((46, 117), "C", font=self.font_small, fill=RED)
        self.draw.text((54, 117), "Photo", font=self.font_small, fill=(0, 0, 128))
        self.draw.rectangle([88, 118, 128, 128], fill=(0, 0, 32))
        self.draw.text((90, 117), "D", font=self.font_small, fill=RED)
        self.draw.text((98, 117), "Exit", font=self.font_small, fill=(0, 0, 128))

        return self.screen_update()

