#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains all the UI Module classes

"""

from PiFinder import cat_images
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.ui.base import UIModule
from PiFinder.ui.ui_utils import (
    TextLayouterScroll,
    TextLayouter,
    TextLayouterSimple,
    SpaceCalculatorFixed,
    name_deduplicate,
)
from PiFinder import calc_utils
import functools

from PiFinder.db.observations_db import ObservationsDatabase


# Constants for display modes
DM_DESC = 0  # Display mode for description
DM_POSS = 1  # Display mode for POSS
DM_SDSS = 2  # Display mode for SDSS


class UIObjectDetails(UIModule):
    """
    Shows details about an object
    """

    __title__ = "OBJECT"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.screen_direction = self.config_object.get_option("screen_direction")
        self.mount_type = self.config_object.get_option("mount_type")
        self.object = self.item_definition["object"]

        self.object_display_mode = DM_DESC
        self.object_image = None

        self.fov_list = [1, 0.5, 0.25, 0.125]
        self.fov_index = 0

        # Used for displaying obsevation counts
        self.observations_db = ObservationsDatabase()

        self.object_text = ["No Object Found"]
        self.simpleTextLayout = functools.partial(
            TextLayouterSimple,
            draw=self.draw,
            color=self.colors.get(255),
            font=self.fonts.base,
        )
        self.descTextLayout: TextLayouter = TextLayouter(
            "",
            draw=self.draw,
            color=self.colors.get(255),
            colors=self.colors,
            font=self.fonts.base,
        )
        self.ScrollTextLayout = functools.partial(
            TextLayouterScroll,
            draw=self.draw,
            color=self.colors.get(255),
            font=self.fonts.base,
        )
        self.space_calculator = SpaceCalculatorFixed(18)
        self.texts = {
            "type-const": self.simpleTextLayout(
                "No Object Found",
                font=self.fonts.bold,
                color=self.colors.get(255),
            ),
        }

        self.update_object_info()

    def _layout_designator(self):
        """
        Generates designator layout object
        If there is a selected object which
        is in the catalog, but not in the filtered
        catalog, dim the designator out
        """
        designator_color = 255
        if not self.object.last_filtered_result:
            designator_color = 128
        return self.simpleTextLayout(
            self.object.display_name,
            font=self.fonts.large,
            color=self.colors.get(designator_color),
        )

    def refresh_designator(self):
        self.texts["designator"] = self._layout_designator()

    def _get_scrollspeed_config(self):
        scroll_dict = {
            "Off": 0,
            "Fast": TextLayouterScroll.FAST,
            "Med": TextLayouterScroll.MEDIUM,
            "Slow": TextLayouterScroll.SLOW,
        }
        scrollspeed = self._config_options["Scrolling"]["value"]
        return scroll_dict[scrollspeed]

    def update_config(self):
        if self.texts.get("aka"):
            self.texts["aka"].set_scrollspeed(self._get_scrollspeed_config())

    def update_object_info(self):
        """
        Generates object text and loads object images
        """
        if self.object_display_mode == DM_DESC:
            # text stuff....

            self.texts = {}
            # Type / Constellation
            object_type = OBJ_TYPES.get(self.object.obj_type, self.object.obj_type)

            # layout the type - constellation line
            _, typeconst = self.space_calculator.calculate_spaces(
                object_type, self.object.const
            )
            self.texts["type-const"] = self.simpleTextLayout(
                typeconst,
                font=self.fonts.bold,
                color=self.colors.get(255),
            )
            # Magnitude / Size
            # try to get object mag to float
            try:
                obj_mag = float(self.object.mag)
            except (ValueError, TypeError):
                obj_mag = "-" if self.object.mag == "" else self.object.mag

            size = str(self.object.size).strip()
            size = "-" if size == "" else size
            # Only construct mag/size if at least one is present
            magsize = ""
            if size != "-" or obj_mag != "-":
                spaces, magsize = self.space_calculator.calculate_spaces(
                    f"Mag:{obj_mag}", f"Sz:{size}"
                )
                if spaces == -1:
                    spaces, magsize = self.space_calculator.calculate_spaces(
                        f"Mag:{obj_mag}", size
                    )
                if spaces == -1:
                    spaces, magsize = self.space_calculator.calculate_spaces(
                        obj_mag, size
                    )

            self.texts["magsize"] = self.simpleTextLayout(
                magsize, font=self.fonts.bold, color=self.colors.get(255)
            )

            if self.object.names:
                # first deduplicate the aka's
                dedups = name_deduplicate(self.object.names, [self.object.display_name])
                self.texts["aka"] = self.ScrollTextLayout(
                    ", ".join(dedups),
                    font=self.fonts.base,
                    scrollspeed=self._get_scrollspeed_config(),
                )

            # NGC description....
            logs = self.observations_db.get_logs_for_object(self.object)
            desc = self.object.description.replace("\t", " ") + "\n"
            if len(logs) == 0:
                desc = desc + "  Not Logged"
            else:
                desc = desc + f"  {len(logs)} Logs"

            self.descTextLayout.set_text(desc)
            self.texts["desc"] = self.descTextLayout

        else:
            # Image stuff...
            if self.object_display_mode == DM_SDSS:
                source = "SDSS"
            else:
                source = "POSS"

            solution = self.shared_state.solution()
            roll = 0
            if solution:
                roll = solution["Roll"]

            self.object_image = cat_images.get_display_image(
                self.object,
                source,
                self.fov_list[self.fov_index],
                roll,
                self.display_class,
            )

    def active(self):
        pass

    def update(self, force=True):
        # Clear Screen
        self.clear_screen()

        if self.object_display_mode == DM_DESC or self.object is None:
            # catalog and entry field i.e. NGC-311
            self.refresh_designator()
            desc_available_lines = 3
            desig = self.texts["designator"]
            desig.draw((0, 21))

            # Object TYPE and Constellation i.e. 'Galaxy    PER'
            typeconst = self.texts.get("type-const")
            if typeconst:
                typeconst.draw((0, 48))

            # Object Magnitude and size i.e. 'Mag:4.0   Sz:7"'
            magsize = self.texts.get("magsize")
            posy = 62
            if magsize and magsize.text.strip():
                if self.object:
                    # check for visibility and adjust mag/size text color
                    obj_altitude = calc_utils.calc_object_altitude(
                        self.shared_state, self.object
                    )

                    if obj_altitude:
                        if obj_altitude < 10:
                            # Not really visible
                            magsize.set_color = self.colors.get(128)
                magsize.draw((0, posy))
                posy += 17
            else:
                posy += 3
                desc_available_lines += 1  # extra lines for description

            # Common names for this object, i.e. M13 -> Hercules cluster
            aka = self.texts.get("aka")
            if aka and aka.text.strip():
                aka.draw((0, posy))
                posy += 11
            else:
                desc_available_lines += 1  # extra lines for description

            # Remaining lines with object description
            desc = self.texts.get("desc")
            if desc:
                desc.set_available_lines(desc_available_lines)
                desc.draw((0, posy))

        else:
            self.screen.paste(self.object_image)
        return self.screen_update()

    def key_down(self):
        # switch object display text
        self.object_display_mode = (
            self.object_display_mode + 1 if self.object_display_mode < 2 else 0
        )
        self.update_object_info()
        self.update()

    def key_up(self):
        # switch object display text
        self.object_display_mode = (
            self.object_display_mode - 1 if self.object_display_mode > 0 else 0
        )
        self.update_object_info()
        self.update()

    def change_fov(self, direction):
        self.fov_index += direction
        if self.fov_index < 0:
            self.fov_index = 0
        if self.fov_index >= len(self.fov_list):
            self.fov_index = len(self.fov_list) - 1
        self.update_object_info()
        self.update()

    def key_plus(self):
        if self.object_display_mode == DM_DESC:
            self.scroll_obj(-1)
        else:
            self.change_fov(-1)

    def key_minus(self):
        if self.object_display_mode == DM_DESC:
            self.scroll_obj(1)
        else:
            self.change_fov(1)
