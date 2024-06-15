#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import time

from PiFinder.ui.base import UIModule
from PiFinder.ui.menu import UIMenu
from PiFinder.menu import MenuScroller
import logging


class UIConfig(UIModule):
    """
    General module for displaying/altering a config
    structure.

    Takes a reference to a UIModule class and
    configures it via user interaction
    """

    __title__ = "OPTIONS"

    def __init__(self, *args):
        self._module = None
        self._selected_item = None
        self._selected_item_key = None
        self._menu = None
        self._mode = "option"
        super().__init__(*args)

    def get_module(self):
        return self._module

    def set_module(self, module):
        """
        Sets the module to configure
        """
        self._module = module
        self._config = module._config_options
        self._mode = "option"
        if self._config:
            self._item_names = list(self._config.keys())

        self._options_menu = UIMenu(
            menu_type="single",
            menu_items=self._item_names,
            selected_items=None,
            back_callback=self.menu_back,
            select_callback=self.menu_select,
            display_class=self.display_class,
            camera_image=None,
            shared_state=self.shared_state,
            command_queues=None,
            config_object=None,
        )
        self._menu = self._options_menu

    def menu_back(self, selection):
        if self._mode == "option":
            self._module.update_config()
            self.switch_to = self._module.__class__.__name__
        else:
            if self._current_config_item["type"] == "multi_enum":
                self._current_config_item["value"] = selection
            self._mode = "option"
            self._menu = self._options_menu

    def menu_select(self, selection):
        if self._mode == "option":
            self._mode = "value"
            self._current_config_item = self._config[selection]

            _menu_type = "single"
            _selected_items = self._current_config_item["value"]
            if self._current_config_item["type"] == "multi_enum":
                _menu_type = "multi"
                _selected_items = self._current_config_item["value"]

            self._menu = UIMenu(
                menu_type=_menu_type,
                menu_items=self._current_config_item["options"],
                selected_items=_selected_items,
                back_callback=self.menu_back,
                select_callback=self.menu_select,
                display_class=self.display_class,
                camera_image=None,
                shared_state=self.shared_state,
                command_queues=None,
                config_object=None,
            )
        else:
            self._current_config_item["value"] = selection
            self.menu_back(selection)

    def update(self, force=False):
        time.sleep(1 / 30)
        self._menu.update()
        _switch_to = self.switch_to
        self.switch_to = None
        return _switch_to

    def key_enter(self):
        # No matter where we are, enter should clear
        # any selected item
        self._menu.key_enter()

    def key_up(self):
        self._menu.key_up()

    def key_down(self):
        self._menu.key_down()

    def key_d(self):
        self._menu.key_d()

    def active(self):
        self._selected_item = None
        self._selected_item_key = None
