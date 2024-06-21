#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module holds some callbacks
used by the menu system

Each one takes the current ui module as an argument

"""

import datetime

from PiFinder.ui.base import UIModule
from PiFinder.catalogs import CatalogFilter


def go_back(ui_module: UIModule) -> None:
    """
    Just removes the current ui module fom the stack
    """
    ui_module.remove_from_stack()
    return


def reset_filters(ui_module: UIModule) -> None:
    """
    Reset all filters to default
    """

    ui_module.catalogs.set_catalog_filter(
        CatalogFilter(shared_state=ui_module.shared_state)
    )
    ui_module.config_object.reset_filters()
    ui_module.catalogs.filter_catalogs()
    ui_module.message("Filters Reset")
    ui_module.remove_from_stack()
    return


def activate_debug(ui_module: UIModule) -> None:
    """
    Sets camera into debug
    add fake gps info
    """
    ui_module.command_queues["camera"].put("debug")
    ui_module.command_queues["console"].put("Debug: Activated")
    dt = datetime.datetime(2024, 6, 1, 2, 0, 0)
    ui_module.shared_state.set_datetime(dt)
    ui_module.message("Test Mode")
