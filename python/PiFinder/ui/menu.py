#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import time

from PiFinder.ui.base import UIModule
from PiFinder.menu import MenuScroller
import logging


class UIMenu(UIModule):
    """
    General module for displaying/altering a config
    structure.

    Takes a reference to a UIModule class and
    configures it via user interaction
    """

    __title__ = "OPTIONS"

    def __init__(self, *args):
        self._module = None
        self._selected_item_index = None
        super().__init__(*args)

    def get_module(self):
        return self._module

    def set_module(self, module):
        """
        Sets the module to configure
        """
        self._module = module
        self._config = module._config_options
        if self._config:
            self._item_names = list(self._config.keys())
            self._selected_item_index = 0

    def update(self, force=False):
        # clear screen
        self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))
        if self._config is None:
            self.draw.text(
                (20, 18), "No Config", font=self.font_base, fill=self.colors.get(255)
            )
        else:
            line_number = 0
            for i in range(
                self._selected_item_index - 3, self._selected_item_index + 4
            ):
                # figure out line position / color / font
                line_font = self.font_base
                if line_number == 0:
                    line_color = 96
                    line_pos = 0
                if line_number == 1:
                    line_color = 128
                    line_pos = 13
                if line_number == 2:
                    line_color = 192
                    line_font = self.font_bold
                    line_pos = 25
                if line_number == 3:
                    line_color = 256
                    line_font = self.font_large
                    line_pos = 40
                if line_number == 4:
                    line_color = 192
                    line_font = self.font_bold
                    line_pos = 60
                if line_number == 5:
                    line_color = 128
                    line_pos = 76
                if line_number == 6:
                    line_color = 96
                    line_pos = 89

                # Offset for title
                line_pos += 20

                # figure out line text
                if i < 0:
                    item_text = ""
                elif i >= len(self._item_names):
                    item_text = ""
                else:
                    item_text = self._item_names[i]

                self.draw.text(
                    (5, line_pos),
                    item_text,
                    font=line_font,
                    fill=self.colors.get(line_color),
                )

                line_number += 1

        return self.screen_update()

    def menu_scroll(self, direction: int):
        self._selected_item_index += direction
        if self._selected_item_index < 0:
            self._selected_item_index = 0

        if self._selected_item_index >= len(self._item_names):
            self._selected_item_index = len(self._item_names) - 1

    def key_enter(self):
        # No matter where we are, enter should clear
        # any selected item
        self._selected_item = None

    def key_up(self):
        self.menu_scroll(-1)

    def key_down(self):
        self.menu_scroll(1)

    def active(self):
        self._selected_item = None
        self._selected_item_key = None
