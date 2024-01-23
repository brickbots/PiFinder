#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import time
import timeit
from typing import List

from PiFinder import config
from PiFinder.obj_types import OBJ_TYPES, OBJ_TYPE_MARKERS
from PiFinder.ui.base import UIModule
from PiFinder.ui.fonts import Fonts as fonts
from PiFinder.ui.ui_utils import (
    TextLayouterScroll,
    TextLayouter,
    TextLayouterSimple,
    SpaceCalculatorFixed,
)
from PiFinder.catalogs import (
    CatalogTracker,
)
from PiFinder.calc_utils import aim_degrees, FastAltAz
import functools
import logging

from PiFinder.db.observations_db import ObservationsDatabase
from PiFinder.catalogs import CompositeObject
from PiFinder.ui.catalog import UICatalog
from PiFinder.ui.fonts import Fonts as fonts
from PIL import Image, ImageChops
from pathlib import Path
import os
from PiFinder import utils


class UIBrowsing(UIModule):
    """
    Search catalogs for object to find
    """

    __title__ = "EXPLORE"
    __button_hints__ = {
        "B": "Image",
        "C": "Catalog",
        "D": "More",
    }
    _config_options = {}
    left_arrow = ""
    right_arrow = ""
    up_arrow = ""
    down_arrow = ""

    def __init__(self, ui_catalog: UICatalog, *args):
        super().__init__(*args)
        self.ui_catalog = ui_catalog
        self._config_options = ui_catalog._config_options
        self.catalog_tracker = ui_catalog.catalog_tracker
        self.screen_direction = config.Config().get_option("screen_direction")
        self.mount_type = config.Config().get_option("mount_type")
        self.simpleTextLayout = functools.partial(
            TextLayouterSimple, draw=self.draw, color=self.colors.get(255)
        )
        self.descTextLayout = TextLayouter(
            "",
            draw=self.draw,
            color=self.colors.get(255),
            colors=self.colors,
            font=fonts.base,
        )
        self.ScrollTextLayout = functools.partial(
            TextLayouterScroll, draw=self.draw, color=self.colors.get(255)
        )
        self.space_calculator = SpaceCalculatorFixed(fonts.base_width - 2)
        self.texts = {
            "type-const": self.simpleTextLayout(
                "No Object Found", font=self.font_bold, color=self.colors.get(255)
            ),
        }
        self.closest_objects_text = []
        self.font_large = fonts.large
        self.objects_balltree = None
        self.catalog_tracker.filter()

        marker_path = Path(utils.pifinder_dir, "markers")
        self.markers = {}
        render_size = (11, 11)
        for filename in os.listdir(marker_path):
            if filename.startswith("mrk_"):
                marker_code = filename[4:-4]
                _image = Image.new("RGB", render_size)
                _image.paste(
                    Image.open(f"{marker_path}/mrk_{marker_code}.png"),
                    (0, 0),
                )
                self.markers[marker_code] = ImageChops.multiply(
                    _image, Image.new("RGB", render_size, self.colors.get(256))
                )

    def update_config(self):
        self.ui_catalog.update_config()

    def push_near(self, obj_amount):
        self._config_options["Near Obj."]["value"] = ""
        if obj_amount != "CANCEL":
            solution = self.shared_state.solution()
            if not solution:
                self.message("No Solve!", 1)
                return False

            # Filter the catalogs one last time
            self.catalog_tracker.filter(False)
            near_catalog, _ = self.catalog_tracker.get_closest_objects(
                solution["RA"],
                solution["Dec"],
                obj_amount,
                catalogs=self.catalog_tracker.catalogs,
            )

    def update_object_info(self):
        self.update()

    def format_az_alt(self, point_az, point_alt):
        if point_az >= 0:
            az_arrow_symbol = self.right_arrow
        else:
            point_az *= -1
            az_arrow_symbol = self.left_arrow

        if point_az < 1:
            az_string = f"{az_arrow_symbol}{point_az:04.2f}"
        else:
            az_string = f"{az_arrow_symbol}{point_az:04.1f}"

        if point_alt >= 0:
            alt_arrow_symbol = self.up_arrow
        else:
            point_alt *= -1
            alt_arrow_symbol = self.down_arrow

        if point_alt < 1:
            alt_string = f"{alt_arrow_symbol}{point_alt:04.2f}"
        else:
            alt_string = f"{alt_arrow_symbol}{point_alt:04.1f}"

        return az_string, alt_string

    def _interpolate_color(self, mag):
        """
        choose a color corresponding to the Magnitude
        """
        if mag <= 9:
            return 255
        elif mag >= 16:
            return 125
        else:
            return int(255 + ((125 - 255) / (16 - 9)) * (mag - 9))

    def update_closest(self):
        """
        get the current pointing solution and search the X closest objects
        to that location
        """
        if self.shared_state.solution():
            closest_objects: List[CompositeObject] = None
            if not self.objects_balltree:
                (
                    closest_objects,
                    self.objects_balltree,
                ) = self.catalog_tracker.get_closest_objects(
                    self.shared_state.solution()["RA"],
                    self.shared_state.solution()["Dec"],
                    11,
                    catalogs=self.catalog_tracker.catalogs,
                )
            else:
                closest_objects = self.catalog_tracker.get_closest_objects_cached(
                    self.shared_state.solution()["RA"],
                    self.shared_state.solution()["Dec"],
                    11,
                    self.objects_balltree,
                )

            # logging.debug(f"Closest objects: {closest_objects}")
            closest_objects_text = []
            for obj in closest_objects:
                az, alt = aim_degrees(
                    self.shared_state, self.mount_type, self.screen_direction, obj
                )
                if az:
                    az_txt, alt_txt = self.format_az_alt(az, alt)
                    distance = f"{az_txt} {alt_txt}"
                else:
                    distance = "--.- --.-"
                # logging.debug(f"Closest object dist = {az}, {alt}")
                obj_name = f"{obj.catalog_code}{obj.sequence}"
                _, obj_dist = self.space_calculator.calculate_spaces(
                    obj_name, distance, empty_if_exceeds=False, trunc_left=True
                )
                try:
                    obj_mag = float(obj.mag)
                except (ValueError, TypeError):
                    obj_mag = 99
                entry = self.simpleTextLayout(
                    obj_dist,
                    font=fonts.base,
                    color=self.colors.get(self._interpolate_color(obj_mag)),
                )
                closest_objects_text.append((obj.obj_type, entry))
            self.closest_objects_text = closest_objects_text

    def active(self):
        # trigger refilter
        super().active()
        self.catalog_tracker.filter()
        self.update_object_info()

    def update(self, force=True):
        time.sleep(1 / 30)
        self.update_closest()
        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))
        line = 17
        for obj_type, txt in self.closest_objects_text:
            # logging.debug(f"Drawing closest object text: {txt=} on line {line=} on line {line=}")
            marker = OBJ_TYPE_MARKERS.get(obj_type)
            if marker:
                self.screen.paste(self.markers[marker], (0, line))
            txt.draw((12, line))
            line += 11
        # logging.debug(f"Browsing update, nr text = {len(self.closest_objects_text)}, line={line}")
        # time.sleep(1)
        return self.screen_update()

    def key_d(self):
        pass
        # self.descTextLayout.next()
        # typeconst = self.texts.get("type-const")
        # if typeconst and isinstance(typeconst, TextLayouter):
        #     typeconst.next()

    def delete(self):
        # long d called from main
        self.catalog_tracker.set_current_object(None)
        self.update_object_info()

    def key_c(self):
        pass
        # C is for catalog
        # self.catalog_tracker.next_catalog()
        # self.catalog_tracker.filter()
        # self.update_object_info()
        # self.object_display_mode = DM_DESC

    def key_long_c(self):
        pass
        # self.delete()
        # self.catalog_tracker.previous_catalog()
        # self.catalog_tracker.filter()
        # self.update_object_info()

    def key_b(self):
        pass
        # if self.catalog_tracker.get_current_object() is None:
        #     self.object_display_mode = DM_DESC
        # else:
        #     # switch object display text
        #     self.object_display_mode = (
        #         self.object_display_mode + 1 if self.object_display_mode < 2 else 0
        #     )
        #     self.update_object_info()
        #     self.update()

    def background_update(self):
        if time.time() - self.catalog_tracker.current_catalog.last_filtered > 60:
            self.catalog_tracker.filter()

    # duplicate code in Catalog, but this is a bit different
    def calc_object_altitude(self, obj):
        solution = self.shared_state.solution()
        location = self.shared_state.location()
        dt = self.shared_state.datetime()
        if location and dt and solution:
            aa = FastAltAz(
                location["lat"],
                location["lon"],
                dt,
            )
            obj_alt = aa.radec_to_altaz(
                obj.ra,
                obj.dec,
                alt_only=True,
            )
            return obj_alt

        return None

    def key_enter(self):
        """
        When enter is pressed, set the
        target
        """
        pass
        # cat_object: CompositeObject = self.catalog_tracker.get_current_object()
        # if cat_object:
        #     self.ui_state["target"] = cat_object
        #     if len(self.ui_state["history_list"]) == 0:
        #         self.ui_state["history_list"].append(self.ui_state["target"])
        #     elif self.ui_state["history_list"][-1] != self.ui_state["target"]:
        #         self.ui_state["history_list"].append(self.ui_state["target"])
        #
        #     self.ui_state["active_list"] = self.ui_state["history_list"]
        #     self.switch_to = "UILocate"

    def key_up(self):
        pass

    def key_down(self):
        pass
