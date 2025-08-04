#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains all the UI code for the object details screen

"""

from pydeepskylog.exceptions import InvalidParameterError

from PiFinder import cat_images
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.ui.align import align_on_radec
from PiFinder.ui.base import UIModule
from PiFinder.ui.log import UILog
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
import numpy as np
import time
import pydeepskylog as pds


# Constants for display modes
DM_DESC = 0  # Display mode for description
DM_LOCATE = 1  # Display mode for LOCATE
DM_POSS = 2  # Display mode for POSS
DM_SDSS = 3  # Display mode for SDSS


class UIObjectDetails(UIModule):
    """
    Shows details about an object
    """

    __help_name__ = "object_details"
    __title__ = "OBJECT"
    __ACTIVATION_TIMEOUT = 10

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.contrast = None
        self.screen_direction = self.config_object.get_option("screen_direction")
        self.mount_type = self.config_object.get_option("mount_type")
        self.object = self.item_definition["object"]
        self.object_list = self.item_definition["object_list"]
        self.object_display_mode = DM_LOCATE
        self.object_image = None

        # Marking Menu - Just default help for now
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            right=MarkingMenuOption(),
            down=MarkingMenuOption(
                label=_("ALIGN"),
                callback=MarkingMenu(
                    up=MarkingMenuOption(),
                    left=MarkingMenuOption(label=_("CANCEL"), callback=self.mm_cancel),
                    down=MarkingMenuOption(),
                    right=MarkingMenuOption(label=_("ALIGN"), callback=self.mm_align),
                ),
            ),
        )

        # Used for displaying observation counts
        self.observations_db = ObservationsDatabase()

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
                _("No Object Found"),
                font=self.fonts.bold,
                color=self.colors.get(255),
            ),
        }

        # cache some display stuff for locate
        self.az_anchor = (0, self.display_class.resY - (self.fonts.huge.height * 2.2))
        self.alt_anchor = (0, self.display_class.resY - (self.fonts.huge.height * 1.2))
        self._elipsis_count = 0

        self.active()  # fill in activation time
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

        # layout the name - contrast reserve line
        space_calculator = SpaceCalculatorFixed(14)

        _, typeconst = space_calculator.calculate_spaces(
            self.object.display_name, self.contrast
        )
        return self.simpleTextLayout(
            typeconst,
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
        scrollspeed = self.config_object.get_option("text_scroll_speed", "Med")
        return scroll_dict[scrollspeed]

    def update_config(self):
        if self.texts.get("aka"):
            self.texts["aka"].set_scrollspeed(self._get_scrollspeed_config())

    def update_object_info(self):
        """
        Generates object text and loads object images
        """
        # Title...
        self.title = self.object.display_name

        # text stuff....

        self.texts = {}
        # Type / Constellation
        object_type = OBJ_TYPES.get(self.object.obj_type, self.object.obj_type)

        # layout the type - constellation line
        discarded, typeconst = self.space_calculator.calculate_spaces(  # noqa: F841
            object_type, self.object.const
        )
        self.texts["type-const"] = self.simpleTextLayout(
            _(typeconst),
            font=self.fonts.bold,
            color=self.colors.get(255),
        )
        # Magnitude / Size
        # try to get object mag to float
        obj_mag = self.object.mag_str

        size = str(self.object.size).strip()
        size = "-" if size == "" else size
        # Only construct mag/size if at least one is present
        magsize = ""
        if size != "-" or obj_mag != "-":
            spaces, magsize = self.space_calculator.calculate_spaces(
                _("Mag:{obj_mag}").format(
                    obj_mag=obj_mag
                ),  # TRANSLATORS: object info magnitude
                _("Sz:{size}").format(size=size),  # TRANSLATORS: object info size
            )
            if spaces == -1:
                spaces, magsize = self.space_calculator.calculate_spaces(
                    _("Mag:{obj_mag}").format(obj_mag=obj_mag), size
                )
            if spaces == -1:
                spaces, magsize = self.space_calculator.calculate_spaces(obj_mag, size)

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

        # Get the SQM from the shared state
        sqm = self.shared_state.get_sky_brightness()

        # Check if a telescope and eyepiece are set
        if (
            self.config_object.equipment.active_eyepiece is None
            or self.config_object.equipment.active_eyepiece is None
        ):
            self.contrast = ""
        else:
            # Calculate contrast reserve. The object diameters are given in arc seconds.
            magnification = self.config_object.equipment.calc_magnification(
                self.config_object.equipment.active_telescope,
                self.config_object.equipment.active_eyepiece,
            )
            if self.object.mag_str == "-":
                self.contrast = ""
            else:
                try:
                    if self.object.size:
                        # Check if the size contains 'x'
                        if "x" in self.object.size:
                            diameter1, diameter2 = map(
                                float, self.object.size.split("x")
                            )
                            diameter1 = (
                                diameter1 * 60.0
                            )  # Convert arc seconds to arc minutes
                            diameter2 = diameter2 * 60.0
                        elif "'" in self.object.size:
                            # Convert arc minutes to arc seconds
                            diameter1 = float(self.object.size.replace("'", "")) * 60.0
                            diameter2 = diameter1
                        else:
                            diameter1 = diameter2 = float(self.object.size) * 60.0
                    else:
                        diameter1 = diameter2 = None

                    self.contrast = pds.contrast_reserve(
                        sqm=sqm,
                        telescope_diameter=self.config_object.equipment.active_telescope.aperture_mm,
                        magnification=magnification,
                        surf_brightness=None,
                        magnitude=float(self.object.mag_str),
                        object_diameter1=diameter1,
                        object_diameter2=diameter2,
                    )
                except InvalidParameterError as e:
                    print(f"Error calculating contrast reserve: {e}")
                    self.contrast = ""
        if self.contrast is not None and self.contrast != "":
            self.contrast = f"{self.contrast: .1f}"
        else:
            self.contrast = ""

        # Add contrast reserve line to details with interpretation
        if self.contrast:
            contrast_val = float(self.contrast)
            if contrast_val < -0.2:
                contrast_str = f"Object is not visible"
            elif -0.2 <= contrast_val < 0.1:
                contrast_str = f"Questionable detection"
            elif 0.1 <= contrast_val < 0.35:
                contrast_str = f"Difficult to see"
            elif 0.35 <= contrast_val < 0.5:
                contrast_str = f"Quite difficult to see"
            elif 0.5 <= contrast_val < 1.0:
                contrast_str = f"Easy to see"
            elif contrast_val >= 1.0:
                contrast_str = f"Very easy to see"
            else:
                contrast_str = f""
            self.texts["contrast_reserve"] = self.ScrollTextLayout(
                contrast_str, font=self.fonts.base, color=self.colors.get(255), scrollspeed=self._get_scrollspeed_config(),
            )

        # NGC description....
        logs = self.observations_db.get_logs_for_object(self.object)
        desc = ""
        if self.object.description:
            desc = (
                self.object.description.replace("\t", " ") + "\n"
            )  # I18N: Descriptions are not translated
        if len(logs) == 0:
            desc = desc + _("  Not Logged")
        else:
            desc = desc + _("  {logs} Logs").format(logs=len(logs))

        self.descTextLayout.set_text(desc)
        self.texts["desc"] = self.descTextLayout

        solution = self.shared_state.solution()
        roll = 0
        if solution:
            roll = solution["Roll"]

        magnification = self.config_object.equipment.calc_magnification()
        self.object_image = cat_images.get_display_image(
            self.object,
            str(self.config_object.equipment.active_eyepiece),
            self.config_object.equipment.calc_tfov(),
            roll,
            self.display_class,
            burn_in=self.object_display_mode in [DM_POSS, DM_SDSS],
            magnification=magnification,
        )


    def active(self):
        self.activation_time = time.time()

    def _check_catalog_initialized(self):
        code = self.object.catalog_code
        if code in ["PUSH", "USER"]:
            # Special codes for objects pushed from sky-safari or created by user
            return True
        catalog = self.catalogs.get_catalog_by_code(code)
        return catalog and catalog.initialized

    def _render_pointing_instructions(self):
        # Pointing Instructions
        if self.shared_state.solution() is None:
            self.draw.text(
                (10, 70),
                _("No solve"),  # TRANSLATORS: No solve yet... (Part 1/2)
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 90),
                _("yet{elipsis}").format(
                    elipsis="." * int(self._elipsis_count / 10)
                ),  # TRANSLATORS: No solve yet... (Part 2/2)
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self._elipsis_count += 1
            if self._elipsis_count > 39:
                self._elipsis_count = 0
            return

        if not self.shared_state.altaz_ready():
            self.draw.text(
                (10, 70),
                _("Searching"),  # TRANSLATORS: Searching for GPS (Part 1/2)
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 90),
                _("for GPS{elipsis}").format(
                    elipsis="." * int(self._elipsis_count / 10)
                ),  # TRANSLATORS: Searching for GPS (Part 2/2)
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self._elipsis_count += 1
            if self._elipsis_count > 39:
                self._elipsis_count = 0
            return

        if not self._check_catalog_initialized():
            self.draw.text(
                (10, 70),
                _("Calculating"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 90),
                _(f"positions{'.' * int(self._elipsis_count / 10)}"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self._elipsis_count += 1
            if self._elipsis_count > 39:
                self._elipsis_count = 0
            return

        indicator_color = 255 if self._unmoved else 128
        point_az, point_alt = calc_utils.aim_degrees(
            self.shared_state,
            self.mount_type,
            self.screen_direction,
            self.object,
        )
        if point_az < 0:
            point_az *= -1
            az_arrow = self._LEFT_ARROW
        else:
            az_arrow = self._RIGHT_ARROW

        # Check az arrow config
        if self.config_object.get_option("pushto_az_arrows", "Default") == "Reverse":
            if az_arrow is self._LEFT_ARROW:
                az_arrow = self._RIGHT_ARROW
            else:
                az_arrow = self._LEFT_ARROW

        # Change decimal points when within 1 degree
        if point_az < 1:
            self.draw.text(
                self.az_anchor,
                f"{az_arrow}{point_az : >5.2f}",
                font=self.fonts.huge.font,
                fill=self.colors.get(indicator_color),
            )
        else:
            self.draw.text(
                self.az_anchor,
                f"{az_arrow}{point_az : >5.1f}",
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
                f"{alt_arrow}{point_alt : >5.2f}",
                font=self.fonts.huge.font,
                fill=self.colors.get(indicator_color),
            )
        else:
            self.draw.text(
                self.alt_anchor,
                f"{alt_arrow}{point_alt : >5.1f}",
                font=self.fonts.huge.font,
                fill=self.colors.get(indicator_color),
            )

    def update(self, force=True):
        # Clear Screen
        self.clear_screen()

        # paste image
        if self.object_display_mode in [DM_POSS, DM_SDSS]:
            self.screen.paste(self.object_image)

        if self.object_display_mode == DM_DESC or self.object_display_mode == DM_LOCATE:
            # catalog and entry field i.e. NGC-311
            self.refresh_designator()
            desc_available_lines = 3
            desig = self.texts["designator"]
            desig.draw((0, 20))

            # Object TYPE and Constellation i.e. 'Galaxy    PER'
            typeconst = self.texts.get("type-const")
            if typeconst:
                typeconst.draw((0, 36))

        if self.object_display_mode == DM_LOCATE:
            self._render_pointing_instructions()

        elif self.object_display_mode == DM_DESC:
            # Object Magnitude and size i.e. 'Mag:4.0   Sz:7"'
            magsize = self.texts.get("magsize")
            posy = 52
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

            contrast = self.texts.get("contrast_reserve")

            if contrast and contrast.text.strip():
                contrast.draw((0, posy))
                posy += 11
            else:
                desc_available_lines +=1

            # Remaining lines with object description
            desc = self.texts.get("desc")
            if desc:
                desc.set_available_lines(desc_available_lines)
                desc.draw((0, posy))

        return self.screen_update()

    def cycle_display_mode(self):
        """
        Cycle through available display modes
        for a module.  Invoked when the square
        key is pressed
        """
        self.object_display_mode = (
            self.object_display_mode + 1 if self.object_display_mode < 2 else 0
        )
        self.update_object_info()
        self.update()

    def maybe_add_to_recents(self):
        if self.activation_time < time.time() - self.__ACTIVATION_TIMEOUT:
            self.ui_state.add_recent(self.object)
            self.active()  # reset activation time

    def scroll_object(self, direction: int) -> None:
        if isinstance(self.object_list, np.ndarray):
            # For NumPy array
            current_index = np.where(self.object_list == self.object)[0][0]
        else:
            # For regular Python list
            current_index = self.object_list.index(self.object)
        current_index += direction
        if current_index < 0:
            current_index = 0
        if current_index >= len(self.object_list):
            current_index = len(self.object_list) - 1

        self.object = self.object_list[current_index]
        self.update_object_info()
        self.update()

    def mm_cancel(self, _marking_menu, _menu_item) -> bool:
        """
        Do nothing....
        """
        return True

    def mm_align(self, _marking_menu, _menu_item) -> bool:
        """
        Called from marking menu to align on curent object
        """
        self.message(_("Aligning..."), 0.1)
        if align_on_radec(
            self.object.ra,
            self.object.dec,
            self.command_queues,
            self.config_object,
            self.shared_state,
        ):
            self.message(_("Aligned!"), 1)
        else:
            self.message(_("Too Far"), 2)

        return True

    def key_down(self):
        self.maybe_add_to_recents()
        self.scroll_object(1)

    def key_up(self):
        self.maybe_add_to_recents()
        self.scroll_object(-1)

    def key_left(self):
        self.maybe_add_to_recents()
        return True

    def key_right(self):
        """
        When right is pressed, move to
        logging screen
        """
        self.maybe_add_to_recents()
        if self.shared_state.solution() is None:
            return
        object_item_definition = {
            "name": _("LOG"),
            "class": UILog,
            "object": self.object,
        }
        self.add_to_stack(object_item_definition)

    def change_fov(self, direction):
        self.config_object.equipment.cycle_eyepieces(direction)
        self.update_object_info()
        self.update()

    def key_plus(self):
        if self.object_display_mode == DM_DESC:
            self.descTextLayout.next()
            typeconst = self.texts.get("type-const")
            if typeconst and isinstance(typeconst, TextLayouter):
                typeconst.next()
        else:
            self.change_fov(1)

    def key_minus(self):
        if self.object_display_mode == DM_DESC:
            self.descTextLayout.next()
            typeconst = self.texts.get("type-const")
            if typeconst and isinstance(typeconst, TextLayouter):
                typeconst.next()
        else:
            self.change_fov(-1)
