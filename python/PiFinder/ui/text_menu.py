#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""

from typing import Union
from PiFinder.ui.base import UIModule
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu


class UITextMenu(UIModule):
    """
    General module for displaying a scrolling
    text list

    """

    __help_name__ = "menu"

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._current_item_index = self.item_definition.get("start_index", 0)
        self._menu_items = [x["name"] for x in self.item_definition["items"]]
        self._menu_type = self.item_definition["select"]

        # Marking menu definition
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            down=MarkingMenuOption(
                label="Shutdown",
                menu_jump="shutdown",
            ),
            right=MarkingMenuOption(),
        )

        self._selected_values = []
        if self.item_definition.get("value_callback"):
            self._selected_values = self.item_definition.get("value_callback")(self)
            # Set current item index based on selection
            for i, _item in enumerate(self.item_definition["items"]):
                if _item["value"] == self._selected_values[0]:
                    self._current_item_index = i

        if config_option := self.item_definition.get("config_option"):
            if self._menu_type == "multi":
                self._selected_values = self.config_object.get_option(config_option)
                if self._selected_values is None:
                    # None means 'all selected' in many filter cases
                    # so select them all
                    self._selected_values = [
                        x["value"] for x in self.item_definition["items"]
                    ]
                self._menu_items = [
                    _("Select None")
                ] + self._menu_items  # TRANSLATORS: catalog filter deselect all
            else:
                self._selected_values = [self.config_object.get_option(config_option)]
                if self._selected_values == [None]:
                    # default to the first option... just in case
                    self._selected_values = [self.item_definition["items"][0]["value"]]

                # Set current item index based on selection
                for i, _item in enumerate(self.item_definition["items"]):
                    if _item["value"] == self._selected_values[0]:
                        self._current_item_index = i

    def update(self, force=False):
        # clear screen
        self.clear_screen()
        # Draw current selection hint
        self.draw.rectangle((-1, 60, 129, 80), outline=self.colors.get(128), width=1)

        line_number = 0
        line_horiz_pos = 13

        for i in range(self._current_item_index - 3, self._current_item_index + 4):
            if i >= 0 and i < self.get_nr_of_menu_items():
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
                item_text = str(self._menu_items[i])

                self.draw.text(
                    (line_horiz_pos, line_pos),
                    _(item_text),  # I18N: translate item for display.
                    font=line_font.font,
                    fill=self.colors.get(line_color),
                )
                if (
                    self.get_item(item_text) is not None
                    and self.get_item(item_text).get("value", "--")
                    in self._selected_values
                ):
                    self.draw.text(
                        (3, line_pos),
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

        if self._current_item_index >= self.get_nr_of_menu_items():
            self._current_item_index = self.get_nr_of_menu_items() - 1

    def get_item(self, item_name: str) -> Union[dict, None]:
        """
        Takes an item name and returns the actual item dict
        """
        for item in self.item_definition["items"]:
            if item["name"] == item_name:
                return item

        return None

    def get_nr_of_menu_items(self):
        return len(self._menu_items)

    def key_right(self):
        """
        This is the main selection function responsible
        for either adjusting configurations, or
        passing in a new UI module definition to add to
        the stack
        """
        selected_item = self._menu_items[self._current_item_index]
        selected_item_definition = self.get_item(selected_item)

        # Is there a callback?
        if selected_item_definition is not None and selected_item_definition.get(
            "callback"
        ):
            # All ui callback functions take the current UI module
            # as an argument, so call it with self here
            return selected_item_definition["callback"](self)

        # If the item has a class, always invoke that class
        if selected_item_definition is not None and selected_item_definition.get(
            "class"
        ):
            # Check for pre_callback before adding to stack
            if selected_item_definition.get("pre_callback"):
                selected_item_definition["pre_callback"](self)
            self.add_to_stack(selected_item_definition)
            return

        # Is this a configuration item menu?
        if config_option := self.item_definition.get("config_option"):
            if self._menu_type == "single":
                config_value = selected_item_definition["value"]
                self._selected_values = [config_value]
                self.config_object.set_option(config_option, config_value)

                # is this a filter option?
                if config_option.startswith("filter."):
                    filter_attr = config_option.split(".")[-1]
                    setattr(self.catalogs.catalog_filter, filter_attr, config_value)

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
                    self._menu_items[0] = _(
                        "Select All"
                    )  # TRANSLATORS: catalog filter select all catalogs

                elif (
                    self.get_item(selected_item).get("value", "--")
                    in self._selected_values
                ):
                    self._selected_values.remove(self.get_item(selected_item)["value"])
                else:
                    self._selected_values.append(self.get_item(selected_item)["value"])

                self.config_object.set_option(config_option, self._selected_values)
                # are we setting active catalogs
                if config_option == "filter.selected_catalogs":
                    self.catalogs.select_no_catalogs()
                    self.catalogs.select_catalogs(self._selected_values)
                    self.catalogs.catalog_filter.selected_catalogs = (
                        self._selected_values
                    )

                # is this a filter option?
                if config_option.startswith("filter."):
                    filter_attr = config_option.split(".")[-1]
                    setattr(
                        self.catalogs.catalog_filter, filter_attr, self._selected_values
                    )

        # Is there a post_callback for this current MENU
        if self.item_definition.get("post_callback"):
            # All ui callback functions take the current UI module
            # as an argument, so call it with self here
            return self.item_definition["post_callback"](self)

    def key_up(self):
        self.menu_scroll(-1)

    def key_down(self):
        self.menu_scroll(1)
