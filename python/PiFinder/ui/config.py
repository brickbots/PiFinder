#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import time

from PiFinder.ui.base import UIModule

RED = (0, 0, 255)


class UIConfig(UIModule):
    """
    General module for displaying/altering a config
    structure.

    Takes a reference to a UIModule class and
    configures it via user interaction
    """

    __title__ = "OPTIONS"

    def __init__(self, *args):
        self.__module = None
        self.__selected_item = None
        self.__selected_item_key = None
        super().__init__(*args)

    def get_module(self):
        return self.__module

    def set_module(self, module):
        """
        Sets the module to configure
        """
        self.__module = module
        self.__config = module._config_options
        if self.__config:
            self.__item_names = list(self.__config.keys())

    def update(self, force=False):
        # clear screen
        self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))
        if self.__config == None:
            self.draw.text((20, 18), "No Config", font=self.font_base, fill=(0, 0, 255))
        else:
            # Draw left side item labels
            selected_index = 0
            for i, item_name in enumerate(self.__item_names):
                if not self.__selected_item:
                    self.draw.text(
                        (0, i * 11 + 18), str(i), font=self.font_base, fill=(0, 0, 255)
                    )

                text_intensity = 128
                if item_name == self.__selected_item:
                    # Highlighted
                    text_intensity = 255
                    # Track the line number for the selected items
                    # this allows us to cluster options around it nicely
                    selected_index = i
                elif self.__selected_item:
                    # disabled
                    text_intensity = 64

                self.draw.text(
                    (10, i * 11 + 18),
                    f"{item_name[:9]: >9}",
                    font=self.font_base,
                    fill=(0, 0, text_intensity),
                )

            # Draw the right side
            if not self.__selected_item:
                # just show values
                i = 0
                for k, v in self.__config.items():
                    value = v["value"]
                    if isinstance(value, list):
                        if len(value) == 1:
                            value = value[0]
                        else:
                            value = "-MULT-"
                    self.draw.text(
                        (70, i * 11 + 18),
                        f"{str(value)[:8]: >8}",
                        font=self.font_base,
                        fill=(0, 0, 128),
                    )
                    i += 1
            else:
                # something is selected, so show the appropriate input
                # mechanism
                selected_item = self.__config[self.__selected_item]
                # Bool
                if selected_item["type"] == "bool":
                    self.draw.text(
                        (70, selected_index * 11 + 18),
                        f"{str(selected_item['value'])[:8]: >8}",
                        font=self.font_base,
                        fill=(0, 0, 255),
                    )

                if "enum" in selected_item["type"]:
                    # Fan out the options around the selected item index
                    option_count = len(selected_item["options"])
                    start_index = selected_index - int(option_count / 2)
                    end_index = selected_index + int(option_count / 2)
                    if end_index > 10:
                        start_index = start_index - (end_index - 10)
                    if start_index < 0:
                        start_index = 0

                    # Show the options
                    for i, enum in enumerate(selected_item["options"]):
                        text_intensity = 128
                        value = selected_item["value"]

                        # convert singles to a list, just to enable the
                        # in check below
                        if selected_item["type"] == "enum":
                            value = [value]

                        if enum in value:
                            # Highlighted
                            text_intensity = 255

                        # enum
                        self.draw.text(
                            (70, (i + start_index) * 11 + 18),
                            f"{str(enum)[:8]: >8}",
                            font=self.font_base,
                            fill=(0, 0, text_intensity),
                        )

                        # number
                        self.draw.text(
                            (122, (i + start_index) * 11 + 18),
                            f"{i}",
                            font=self.font_base,
                            fill=(0, 0, 255),
                        )
        return self.screen_update()

    def key_enter(self):
        # No matter where we are, enter should clear
        # any selected item
        self.__selected_item = None

    def key_number(self, number):
        if self.__selected_item:
            # select the option
            selected_item = self.__config[self.__selected_item]
            if number >= len(selected_item["options"]):
                # if a number is pressed that is not an option
                # just return
                return
            if selected_item["type"] == "enum":
                selected_item["value"] = selected_item["options"][number]
                self.__selected_item = None

            if selected_item["type"] == "multi_enum":
                selected_option = selected_item["options"][number]
                if selected_option == "None":
                    selected_item["value"] = ["None"]
                elif selected_option in selected_item["value"]:
                    selected_item["value"].remove(selected_option)
                else:
                    selected_item["value"].append(selected_option)

                # remove none if there are any other selections
                if len(selected_item["value"]) > 1 and "None" in selected_item["value"]:
                    selected_item["value"].remove("None")

            # Now that we have set config, see if there is a callback
            if selected_item.get("callback") != None:
                callback_method = getattr(self.__module, selected_item["callback"])
                exit_config = callback_method(selected_item["value"])
                if exit_config:
                    if exit_config == True:
                        self.switch_to = self.__module.__class__.__name__
                    else:
                        # there is another module to swith to
                        self.switch_to = exit_config

        else:
            if number >= len(self.__item_names):
                return
            self.__selected_item = self.__item_names[number]
            selected_item = self.__config[self.__selected_item]
            if selected_item["type"] == "bool":
                if selected_item["value"] == "On":
                    selected_item["value"] = "Off"
                else:
                    selected_item["value"] = "On"
                self.update()
                # sleep for a sec to give the user time to see the change
                time.sleep(1)
                # okay, reset and release
                self.__selected_item = None
                if selected_item.get("callback") != None:
                    callback_method = getattr(self.__module, selected_item["callback"])
                    exit_config = callback_method(selected_item["value"])
                    if exit_config:
                        self.switch_to = self.__module.__class__.__name__

    def active(self):
        self.__selected_item = None
        self.__selected_item_key = None
