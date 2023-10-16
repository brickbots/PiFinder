#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import os
import datetime

from PIL import Image
from PiFinder.ui.base import UIModule
from PiFinder.image_util import convert_image_to_mode


class UIConsole(UIModule):
    __title__ = "CONSOLE"

    def __init__(self, *args):
        super().__init__(*args)
        self.dirty = True
        self.welcome = True

        # load welcome image to screen
        root_dir = os.path.realpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        welcome_image_path = os.path.join(root_dir, "images", "welcome.png")
        welcome_image = Image.open(welcome_image_path)
        welcome_image = convert_image_to_mode(welcome_image, self.colors.mode)
        self.screen.paste(welcome_image)

        self.lines = ["---- TOP ---", "Sess UUID:" + self.__uuid__]
        self.scroll_offset = 0
        self.debug_mode = False

    def set_shared_state(self, shared_state):
        self.shared_state = shared_state

    def key_number(self, number):
        if number == 0:
            self.command_queues["camera"].put("debug")
            if self.debug_mode:
                self.debug_mode = False
            else:
                self.debug_mode = True
            self.command_queues["console"].put("Debug: " + str(self.debug_mode))
        dt = datetime.datetime(2022, 11, 15, 2, 0, 0)
        self.shared_state.set_datetime(dt)

    def key_enter(self):
        # reset scroll offset
        self.scroll_offset = 0
        self.dirty = True

    def key_up(self):
        self.scroll_offset += 1
        self.dirty = True

    def key_down(self):
        self.scroll_offset -= 1
        if self.scroll_offset < 0:
            self.scroll_offset = 0
        self.dirty = True

    def write(self, line):
        """
        Writes a new line to the console.
        """
        print(f"Write: {line}")
        self.lines.append(line)
        # reset scroll offset
        self.scroll_offset = 0
        self.dirty = True

    def active(self):
        self.welcome = False
        self.dirty = True
        self.update()

    def update(self, force=False):
        if self.dirty:
            if self.welcome:
                # Clear / write just top line
                self.draw.rectangle(
                    [0, 0, 128, self._title_bar_y], fill=self.colors.get(0)
                )
                self.draw.text(
                    (0, 1),
                    self.lines[-1],
                    font=self.font_base,
                    fill=self.colors.get(255),
                )
                return self.screen_update(title_bar=False)
            else:
                # clear screen
                self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))
                for i, line in enumerate(self.lines[-10 - self.scroll_offset :][:10]):
                    self.draw.text(
                        (0, i * 10 + 20),
                        line,
                        font=self.font_base,
                        fill=self.colors.get(255),
                    )
                self.dirty = False
                return self.screen_update()
