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

        self._menu = UIMenu(
            menu_type="multi",
            menu_items=self._item_names,
            selected_items=[],
            back_callback=self.menu_back,
            select_callback=self.menu_select,
            device_wrapper=self.device_wrapper,
            camera_image=None,
            shared_state=self.shared_state,
            command_queues=None,
            config_object=None,
        )

    def menu_back(self, selection):
        pass

    def menu_select(self, selection):
        pass

    def update(self, force=False):
        self._menu.update()

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
