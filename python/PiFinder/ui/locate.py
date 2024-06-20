#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains the Locate module

"""

import time
import logging

from PiFinder import obslist, config
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.ui.base import UIModule
from PiFinder.ui.catalog import UICatalog
from PiFinder.calc_utils import aim_degrees


class UILocate(UIModule):
    """
    Display pushto info
    """

    __title__ = "LOCATE"
    __button_hints__ = {
        "B": "Histry",
        "C": "Observ",
        "D": "Remove",
    }

    _config_options = {
        "Save": {
            "type": "enum",
            "value": "",
            "options": ["CANCEL", "History", "Observ"],
            "callback": "save_list",
        },
        "Load": {
            "type": "enum",
            "value": "",
            "options": [],
            "callback": "load_list",
        },
    }

    def __init__(self, ui_catalog: UICatalog, *args):
        super().__init__(*args)
        self.target_index = None
        self.object_text = ["No Object Found"]
        self.screen_direction = config.Config().get_option("screen_direction")
        self.mount_type = config.Config().get_option("mount_type")

        available_lists = obslist.get_lists()
        self._config_options["Load"]["options"] = ["CANCEL"] + available_lists
        self.obs_list_write_index = 0
        self.last_update_time = time.time()
        self.ui_catalog = ui_catalog

        # cache some display stuff

        self.az_anchor = (25, self.display_class.resY - (self.fonts.huge.height * 2.2))
        self.alt_anchor = (25, self.display_class.resY - (self.fonts.huge.height * 1.1))
        self._elipsis_count = 0

    def save_list(self, option):
        self._config_options["Load"]["value"] = ""
        if option == "CANCEL":
            return False

        if len(self.ui_state.active_list()) == 0:
            self.message("No objects")
            return False

        filename = f"{self.__uuid__}_{option}_{self.ss_count:02d}"
        if option == "History":
            obslist.write_list(self.ui_state.history_list(), filename)
        else:
            obslist.write_list(self.ui_state.observing_list(), filename)
        self.obs_list_write_index += 1
        self.message(f"Saved list - {self.ss_count:02d}")
        return True

    def load_list(self, option):
        self._config_options["Load"]["value"] = ""
        if option == "CANCEL":
            return False

        _load_results = obslist.read_list(self.ui_catalog.catalogs, option)
        if _load_results["result"] == "error":
            self.message(f"Err! {_load_results['message']}")
            return False

        object_count = len(_load_results["catalog_objects"])
        if object_count == 0:
            self.message("No matches")
            return False

        self.ui_state.set_observing_list(_load_results["catalog_objects"])
        self.ui_state.set_active_list_to_observing_list()
        self.target_index = 0
        self.ui_state.set_target(self.ui_state.active_list()[self.target_index])
        self.update_object_text()
        self.message(f"Loaded {object_count} of {_load_results['objects_parsed']}")
        return True

    def key_b(self):
        """
        When B is pressed, switch to history
        """
        self.target_index = None
        if self.ui_state.active_list_is_history_list():
            pass
        else:
            if len(self.ui_state.history_list()) > 0:
                self.ui_state.set_active_list_to_history_list()
                self.target_index = len(self.ui_state.active_list()) - 1
            else:
                self.message("No History", 1)

        if self.target_index is not None:
            self.ui_state.set_target_to_active_list_index(self.target_index)
            self.update_object_text()

    def key_c(self):
        """
        When C is pressed, switch to observing list
        """
        if self.ui_state.active_list_is_observing_list():
            pass
        else:
            if len(self.ui_state.observing_list()) > 0:
                self.ui_state.set_active_list_to_observing_list()
                self.target_index = 0
            else:
                self.message("No Obs List", 1)

        if self.target_index is not None:
            self.ui_state.set_target_to_active_list_index(self.target_index)
            self.update_object_text()

    def key_enter(self):
        """
        When enter is pressed, set the
        target
        """
        self.switch_to = "UICatalog"

    def key_up(self):
        self.scroll_target_history(-1)

    def key_down(self):
        self.scroll_target_history(1)

    def key_long_d(self):
        active_list = self.ui_state.active_list()
        if self.target_index is not None and len(active_list) > 1:
            del active_list[self.target_index]
            self.target_index = (self.target_index + 1) % len(active_list)
            self.ui_state.set_target_to_active_list_index(self.target_index)
            self.update_object_text()
            self.update()
        elif len(active_list) == 1:
            self.ui_state.set_active_list([])
            self.target_index = None
            self.switch_to = "UICatalog"
        else:
            self.switch_to = "UICatalog"

    def update_object_text(self):
        """
        Generates object text
        """
        target = self.ui_state.target()
        if not target:
            self.object_text = ["No Object Found"]
            return

        self.object_text = []
        try:
            # Type / Constellation
            object_type = OBJ_TYPES.get(target.obj_type, target.obj_type)
            self.object_text.append(f"{object_type: <14} {target.const}")
        except Exception as e:
            logging.error(f"Error generating object text: {e}, {target}")

    def active(self):
        super().active()
        available_lists = obslist.get_lists()
        self._config_options["Load"]["options"] = ["CANCEL"] + available_lists
        try:
            self.target_index = self.ui_state.active_list().index(
                self.ui_state.target()
            )
        except ValueError:
            self.target_index = None
        self.update_object_text()
        self.update()

    def update(self, force=False):
        time.sleep(1 / 30)
        self.clear_screen()

        target = self.ui_state.target()
        if not target:
            self.draw.text(
                (0, self.display_class.titlebar_height + 2),
                "No Target Set",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return self.screen_update()

        # Target Name
        line = target.catalog_code
        line += str(target.sequence)
        self.draw.text(
            (0, self.display_class.titlebar_height + 2),
            line,
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )

        # Target history index
        if self.target_index is not None:
            if self.ui_state.active_list_is_history_list():
                list_name = "Hist"
            else:
                list_name = "Obsv"
            line = f"{self.target_index + 1}/{len(self.ui_state.active_list())}"
            line = f"{line : >9}"
            self.draw.text(
                (
                    self.display_class.resX - (self.fonts.base.width * 9),
                    self.display_class.titlebar_height + 2,
                ),
                line,
                font=self.fonts.base.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (
                    self.display_class.resX - (self.fonts.base.width * 9),
                    self.display_class.titlebar_height + 2 + self.fonts.base.height,
                ),
                f"{list_name: >9}",
                font=self.fonts.base.font,
                fill=self.colors.get(255),
            )

        # ID Line in BOld
        self.draw.text(
            (0, self.display_class.titlebar_height + self.fonts.large.height),
            self.object_text[0],
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        # Pointing Instructions
        indicator_color = 255 if self._unmoved else 128
        point_az, point_alt = aim_degrees(
            self.shared_state,
            self.mount_type,
            self.screen_direction,
            self.ui_state.target(),
        )
        if not point_az:
            if self.shared_state.solution() is None:
                self.draw.text(
                    (10, 70),
                    "No solve",
                    font=self.font_large,
                    fill=self.colors.get(255),
                )
                self.draw.text(
                    (10, 90),
                    f"yet{'.' * int(self._elipsis_count / 10)}",
                    font=self.font_large,
                    fill=self.colors.get(255),
                )
            else:
                self.draw.text(
                    (10, 70),
                    "Searching",
                    font=self.font_large,
                    fill=self.colors.get(255),
                )
                self.draw.text(
                    (10, 90),
                    f"for GPS{'.' * int(self._elipsis_count / 10)}",
                    font=self.font_large,
                    fill=self.colors.get(255),
                )
            self._elipsis_count += 1
            if self._elipsis_count > 39:
                self._elipsis_count = 0
        else:
            if point_az < 0:
                point_az *= -1
                az_arrow = self._LEFT_ARROW
            else:
                az_arrow = self._RIGHT_ARROW

            # Change decimal points when within 1 degree
            if point_az < 1:
                self.draw.text(
                    self.az_anchor,
                    f"{az_arrow} {point_az : >5.2f}",
                    font=self.fonts.huge.font,
                    fill=self.colors.get(indicator_color),
                )
            else:
                self.draw.text(
                    self.az_anchor,
                    f"{az_arrow} {point_az : >5.1f}",
                    font=self.fonts.huge.font,
                    fill=self.colors.get(indicator_color),
                )

            if point_alt < 0:
                point_alt *= -1
                alt_arrow = self._DOWN_ARROW
            else:
                alt_arrow = self._UP_ARROW

            # Change decimal points when within 1 degree
            if point_alt < 1:
                self.draw.text(
                    self.alt_anchor,
                    f"{alt_arrow} {point_alt : >5.2f}",
                    font=self.fonts.huge.font,
                    fill=self.colors.get(indicator_color),
                )
            else:
                self.draw.text(
                    self.alt_anchor,
                    f"{alt_arrow} {point_alt : >5.1f}",
                    font=self.fonts.huge.font,
                    fill=self.colors.get(indicator_color),
                )

        return self.screen_update()

    def scroll_target_history(self, direction):
        if self.target_index is not None:
            self.target_index += direction
            active_list_len = len(self.ui_state.active_list())
            if self.target_index >= active_list_len:
                self.target_index = active_list_len - 1

            if self.target_index < 0:
                self.target_index = 0

            self.ui_state.set_target_to_active_list_index(self.target_index)
            self.update_object_text()
            self.update()
