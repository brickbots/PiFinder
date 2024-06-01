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
    General module for displaying a menu

    """

    __title__ = "OPTIONS"

    def __init__(
        self,
        menu_type,
        menu_items,
        selected_items,
        back_callback,
        select_callback,
        **kwargs
    ):
        self._module = None
        self._current_item_index = 0
        self._menu_items = menu_items
        self._menu_type = menu_type
        if selected_items is None:
            if self._menu_type == "multi":
                self._selected_items = []
            else:
                self._selected_items = self._menu_items[0]
        else:
            self._selected_items = selected_items
        if self._menu_type == "multi":
            self._menu_items = ["Select None"] + self._menu_items
        else:
            self._current_item_index = self._menu_items.index(self._selected_items)
        self._back_callback = back_callback
        self._select_callback = select_callback
        super().__init__(**kwargs)

    def update(self, force=False):
        # clear screen
        self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))

        # Draw current selection hint
        # self.draw.line([0,80,128,80], width=1, fill=self.colors.get(32))
        self.draw.rectangle([0, 60, 128, 80], fill=self.colors.get(32))
        line_number = 0
        for i in range(self._current_item_index - 3, self._current_item_index + 4):
            # figure out line position / color / font
            line_font = self.fonts.base
            if line_number == 0:
                line_color = 96
                line_pos = 0
            if line_number == 1:
                line_color = 128
                line_pos = 13
            if line_number == 2:
                line_color = 192
                line_font = self.fonts.bold
                line_pos = 25
            if line_number == 3:
                line_color = 256
                line_font = self.fonts.large
                line_pos = 40
            if line_number == 4:
                line_color = 192
                line_font = self.fonts.bold
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
            elif i >= len(self._menu_items):
                item_text = ""
            else:
                item_text = str(self._menu_items[i])

            self.draw.text(
                (15, line_pos),
                item_text,
                font=line_font.font,
                fill=self.colors.get(line_color),
            )
            if self._menu_type == "multi":
                if item_text in self._selected_items:
                    self.draw.text(
                        (5, line_pos),
                        "*",
                        font=line_font.font,
                        fill=self.colors.get(line_color),
                    )

            line_number += 1

        return self.screen_update()

    def menu_scroll(self, direction: int):
        self._current_item_index += direction
        if self._current_item_index < 0:
            self._current_item_index = 0

        if self._current_item_index >= len(self._menu_items):
            self._current_item_index = len(self._menu_items) - 1

    def key_enter(self):
        selected_item = self._menu_items[self._current_item_index]
        if self._menu_type == "single":
            self._select_callback(selected_item)
        else:
            if selected_item == "Select All":
                self._selected_items = self._menu_items[1:]
                self._menu_items[0] = "Select None"
                return

            if selected_item == "Select None":
                self._selected_items = []
                self._menu_items[0] = "Select All"
                return

            if selected_item in self._selected_items:
                self._selected_items.remove(selected_item)
            else:
                self._selected_items.append(selected_item)

    def key_up(self):
        self.menu_scroll(-1)

    def key_down(self):
        self.menu_scroll(1)

    def key_d(self):
        if self._menu_type == "single":
            self._back_callback(self._menu_items[self._current_item_index])
        else:
            print(self._selected_items)
            self._back_callback(self._selected_items)
