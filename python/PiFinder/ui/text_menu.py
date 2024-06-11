#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""

from typing import Union
from PiFinder.ui.base import UIModule


class UITextMenu(UIModule):
    """
    General module for displaying a scrolling
    text list

    """

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._current_item_index = 0
        self._menu_items = [x["name"] for x in self.item_definition["items"]]
        self._menu_type = self.item_definition["select"]

        self._selected_values = []
        if config_option := self.item_definition.get("config_option"):
            if self._menu_type == "multi":
                self._selected_values = self.config_object.get_option(config_option)
                self._menu_items = ["Select None"] + self._menu_items
            else:
                self._selected_values = [self.config_object.get_option(config_option)]
                self._current_item_index = self._menu_items.index(
                    self._selected_values[0]
                )

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
            if (
                self.get_item(item_text) is not None
                and self.get_item(item_text).get("value", "--") in self._selected_values
            ):
                self.draw.text(
                    (5, line_pos),
                    self._CHECKMARK,
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

    def get_item(self, item_name: str) -> Union[dict, None]:
        """
        Takes an item name and returns the actual item dict
        """
        for item in self.item_definition["items"]:
            if item["name"] == item_name:
                return item

        return None

    def key_right(self):
        """
        This is the main selection function responsible
        for either adjusting configurations, or
        passing in a new UI module definition to add to
        the stack
        """
        selected_item = self._menu_items[self._current_item_index]
        selected_item_definition = self.get_item(selected_item)

        # If the item has a class, always invoke that class
        if selected_item_definition is not None and selected_item_definition.get(
            "class"
        ):
            self.add_to_stack(selected_item_definition)
            return

        # Is this a configuration item menu?
        if config_option := self.item_definition.get("config_option"):
            if self._menu_type == "single":
                config_value = selected_item_definition["value"]
                self._selected_values = [config_value]
                self.config_object.set_option(config_option, config_value)
                return
            else:
                if selected_item == "Select All":
                    # Only select items with a value key which represent
                    # configuration values
                    for item in self._menu_items[1:]:
                        item_value = self.get_item(item).get("value")
                        if item_value is not None:
                            self._selected_values.append(item_value)

                    # Uniqify selected values
                    self._selected_values = list(set(self._selected_values))
                    self._menu_items[0] = "Select None"

                elif selected_item == "Select None":
                    # We need to be selective here and ONLY remove
                    # items that are in THIS list/menu as this maybe
                    # a mulit-level selector like Catalogs
                    for item in self._menu_items[1:]:
                        item_value = self.get_item(item).get("value")
                        if (
                            item_value is not None
                            and item_value in self._selected_values
                        ):
                            self._selected_values.remove(item_value)
                    self._menu_items[0] = "Select All"

                elif (
                    self.get_item(selected_item).get("value", "--")
                    in self._selected_values
                ):
                    self._selected_values.remove(self.get_item(selected_item)["value"])
                else:
                    self._selected_values.append(self.get_item(selected_item)["value"])

                self.config_object.set_option(config_option, self._selected_values)

    def key_up(self):
        self.menu_scroll(-1)

    def key_down(self):
        self.menu_scroll(1)
