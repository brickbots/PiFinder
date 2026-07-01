#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains all the UI code for the object details screen

"""

from pydeepskylog.exceptions import InvalidParameterError

from PiFinder import cat_images
from PiFinder.composite_object import MagnitudeObject
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.ui.align import align_on_radec
from PiFinder.ui.base import UIModule
from PiFinder.ui.log import UILog
from PiFinder.ui.ui_utils import (
    TextLayouterScroll,
    TextLayouter,
    TextLayouterSimple,
    SectionedTextLayouter,
    SpaceCalculatorFixed,
    name_deduplicate,
    draw_pointing_instructions,
)
from PiFinder import calc_utils
import functools
import logging

from PiFinder.db.observations_db import ObservationsDatabase
from PiFinder.db.objects_db import ObjectsDatabase
import numpy as np
import time
import pydeepskylog as pds

logger = logging.getLogger("UI.ObjectDetails")


# Read-only handle to the catalog DB, opened once and shared across detail
# views. Used by _other_catalog_descriptions() to pull an object's listings in
# its *other* catalogs (this always runs on the description view). Like the
# per-instance ObservationsDatabase opened below, this read connection lives for
# the life of the UI process and is closed when that process exits.
_objects_db = None


def _catalog_db() -> ObjectsDatabase:
    global _objects_db
    if _objects_db is None:
        _objects_db = ObjectsDatabase()
    return _objects_db


# Constants for display modes
DM_DESC = 0  # Display mode for description
DM_LOCATE = 1  # Display mode for LOCATE
DM_POSS = 2  # Display mode for POSS
DM_SDSS = 3  # Display mode for SDSS
DM_CONTRAST = 4  # Display mode for Contrast Reserve explanation


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
        self.descTextLayout: TextLayouter = SectionedTextLayouter(
            "",
            draw=self.draw,
            color=self.colors.get(160),  # body text dimmer; rules drawn at 255
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

        # Two-line status messages ("No solve", "Searching for GPS"...) shown in
        # place of the az/alt readout; positions derive from resolution + font.
        msg_x = round(self.display_class.resX * 10 / 128)
        msg_y1 = round(self.display_class.resY * 70 / 128)
        self._pointing_msg_anchor_1 = (msg_x, msg_y1)
        self._pointing_msg_anchor_2 = (msg_x, msg_y1 + self.fonts.large.height + 2)
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

    def _other_catalog_descriptions(self) -> dict:
        """
        Descriptions from the object's *other* catalog listings (an object can
        live in NGC, M, Collinder, ...), keyed by designation and ordered as
        stored in the DB.  Empty for virtual objects (planets, comets,
        coordinate list entries), which have no DB row.
        """
        if self.object.object_id is None or self.object.object_id < 0:
            return {}
        rows = _catalog_db().get_catalog_objects_by_object_id(self.object.object_id)
        out: dict = {}
        for row in sorted(rows, key=lambda r: r["id"]):
            if (
                row["catalog_code"] == self.object.catalog_code
                and row["sequence"] == self.object.sequence
            ):
                continue  # the home listing is shown first, unlabeled
            desc = (row["description"] or "").strip()
            if desc:
                out[f"{row['catalog_code']} {row['sequence']}"] = desc
        return out

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
            mag = self.object.mag
            magnitude = (
                mag.filter_mag
                if mag is not None and mag.filter_mag != MagnitudeObject.UNKNOWN_MAG
                else None
            )
            if magnitude is None:
                self.contrast = ""
            else:
                try:
                    size = self.object.size
                    if (
                        size
                        and size.extents
                        and not size.is_vertices
                        and not size.is_segments
                    ):
                        # SizeObject.extents are stored in arcseconds.
                        if len(size.extents) >= 2:
                            diameter1 = float(size.extents[0])
                            diameter2 = float(size.extents[1])
                        else:
                            diameter1 = diameter2 = float(size.extents[0])
                    else:
                        diameter1 = diameter2 = None

                    if diameter1 is None or diameter2 is None:
                        # No usable object size: pydeepskylog can't compute a
                        # contrast reserve without diameters — it logs an ERROR
                        # and *returns* (doesn't raise), so the except below
                        # can't suppress it. Skip the call and leave the
                        # contrast line blank.
                        self.contrast = ""
                    else:
                        self.contrast = pds.contrast_reserve(
                            sqm=sqm,
                            telescope_diameter=self.config_object.equipment.active_telescope.aperture_mm,
                            magnification=magnification,
                            surf_brightness=None,
                            magnitude=magnitude,
                            object_diameter1=diameter1,
                            object_diameter2=diameter2,
                        )
                except (ValueError, TypeError, InvalidParameterError) as e:
                    # mag_str / size are not always plain numbers: double stars
                    # carry component mags like "7.0/9.5", asterisms a size like
                    # "3°", and some objects have no magnitude. float() then
                    # raises ValueError/TypeError; treat it like the "-"
                    # magnitude case above and skip the contrast calc.
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
                contrast_str = "Object is not visible"
            elif -0.2 <= contrast_val < 0.1:
                contrast_str = "Questionable detection"
            elif 0.1 <= contrast_val < 0.35:
                contrast_str = "Difficult to see"
            elif 0.35 <= contrast_val < 0.5:
                contrast_str = "Quite difficult to see"
            elif 0.5 <= contrast_val < 1.0:
                contrast_str = "Easy to see"
            elif contrast_val >= 1.0:
                contrast_str = "Very easy to see"
            else:
                contrast_str = ""
            self.texts["contrast_reserve"] = self.ScrollTextLayout(
                contrast_str,
                font=self.fonts.base,
                color=self.colors.get(255),
                scrollspeed=self._get_scrollspeed_config(),
            )

        # Home description (plus other-catalog and observing list descriptions).
        logs = self.observations_db.get_logs_for_object(self.object)
        sections = [
            (label, text.replace("\t", " "))  # I18N: descriptions not translated
            for label, text in self.object.composed_sections(
                extra_descriptions=self._other_catalog_descriptions()
            )
        ]
        if len(logs) == 0:
            sections.append((None, _("  Not Logged")))
        else:
            sections.append((None, _("  {logs} Logs").format(logs=len(logs))))

        self.descTextLayout.set_sections(sections)
        self.texts["desc"] = self.descTextLayout

        solution = self.shared_state.solution()
        roll = 0
        if solution and solution.has_pointing():
            roll = solution.pointing.aligned.estimate.Roll

        magnification = self.config_object.equipment.calc_magnification()
        flip_image, flop_image = (
            self.config_object.equipment.active_telescope_image_orientation()
        )
        self.object_image = cat_images.get_display_image(
            self.object,
            str(self.config_object.equipment.active_eyepiece),
            self.config_object.equipment.calc_tfov(),
            roll,
            self.display_class,
            burn_in=self.object_display_mode in [DM_POSS, DM_SDSS],
            magnification=magnification,
            show_nsew=self.config_object.get_option("image_nsew", True),
            show_bbox=self.config_object.get_option("image_bbox", True),
            flip_image=flip_image,
            flop_image=flop_image,
        )

    def active(self):
        self.activation_time = time.time()

    def _check_catalog_initialized(self):
        code = self.object.catalog_code
        if code in ["PUSH", "USER", "OBS"]:
            # In-memory objects with no backing catalog: pushed from SkySafari
            # (PUSH), user-created (USER), or observing-list coordinate objects
            # (OBS).  They're always "ready"; there's no catalog to initialize.
            return True
        catalog = self.catalogs.get_catalog_by_code(code)
        return catalog and catalog.initialized

    def _render_pointing_instructions(self):
        # Pointing Instructions
        if not self.shared_state.solution().has_pointing():
            self.draw.text(
                self._pointing_msg_anchor_1,
                _("No solve"),  # TRANSLATORS: No solve yet... (Part 1/2)
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                self._pointing_msg_anchor_2,
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
                self._pointing_msg_anchor_1,
                _("Searching"),  # TRANSLATORS: Searching for GPS (Part 1/2)
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                self._pointing_msg_anchor_2,
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
                self._pointing_msg_anchor_1,
                _("Calculating"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                self._pointing_msg_anchor_2,
                _("positions") + "." * int(self._elipsis_count / 10),
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

        # Check if aim_degrees returned valid values
        if point_az is None or point_alt is None:
            # No valid pointing data available
            self.draw.text(
                self._pointing_msg_anchor_1,
                _("Calculating"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                self._pointing_msg_anchor_2,
                _("position") + "." * int(self._elipsis_count / 10),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self._elipsis_count += 1
            if self._elipsis_count > 39:
                self._elipsis_count = 0
            return

        draw_pointing_instructions(
            self, point_az, point_alt, indicator_color, self.mount_type
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
            desc_available_lines = 4
            # Header lines sit just below the title bar; type/const stacks one
            # large-font line below the designator (derived so they track res).
            desig_y = self.display_class.titlebar_height + 3
            typeconst_y = desig_y + self.fonts.large.height
            desig = self.texts["designator"]
            desig.draw((0, desig_y))

            # Object TYPE and Constellation i.e. 'Galaxy    PER'
            typeconst = self.texts.get("type-const")
            if typeconst:
                typeconst.draw((0, typeconst_y))

        if self.object_display_mode == DM_LOCATE:
            self._render_pointing_instructions()

        elif self.object_display_mode == DM_DESC:
            # Object Magnitude and size i.e. 'Mag:4.0   Sz:7"'
            magsize = self.texts.get("magsize")
            # Start just below the type/const header (derived; 52 on the 128
            # panel, lower on taller panels so it doesn't crowd the header).
            posy = typeconst_y + self.fonts.bold.height + 3
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

        elif self.object_display_mode == DM_CONTRAST:
            # Display contrast reserve explanation page
            y_pos = 20

            # Title
            self.draw.text(
                (0, y_pos),
                _("Contrast Reserve"),
                font=self.fonts.base.font,
                fill=self.colors.get(255),
            )
            y_pos += 14

            # Display the contrast value
            contrast = self.texts.get("contrast_reserve")

            if self.contrast:
                contrast_display = f"CR: {self.contrast}"
                self.draw.text(
                    (0, y_pos),
                    contrast_display,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )
                y_pos += 17

                # Display the interpretation
                if contrast and contrast.text.strip():
                    contrast.draw((0, y_pos))
                    y_pos += 17
            else:
                self.draw.text(
                    (0, y_pos),
                    _("No contrast data"),
                    font=self.fonts.base.font,
                    fill=self.colors.get(128),
                )
                y_pos += 14

            # Add explanation about what CR means
            explanation_lines = [
                _(
                    "CR measures object"
                ),  # TRANSLATORS: Contrast reserve explanation line 1
                _(
                    "visibility based on"
                ),  # TRANSLATORS: Contrast reserve explanation line 2
                _(
                    "sky brightness,"
                ),  # TRANSLATORS: Contrast reserve explanation line 3
                _(
                    "telescope, and EP."
                ),  # TRANSLATORS: Contrast reserve explanation (EP = entrance pupil) line 4
            ]

            for line in explanation_lines:
                self.draw.text(
                    (0, y_pos),
                    line,
                    font=self.fonts.base.font,
                    fill=self.colors.get(200),
                )
                y_pos += 11

        return self.screen_update()

    def cycle_display_mode(self):
        """
        Cycle through available display modes
        for a module.  Invoked when the square
        key is pressed
        """
        # Cycle: LOCATE -> POSS -> DESC -> CONTRAST -> LOCATE
        if self.object_display_mode == DM_LOCATE:
            self.object_display_mode = DM_POSS
        elif self.object_display_mode == DM_POSS:
            self.object_display_mode = DM_DESC
        elif self.object_display_mode == DM_DESC:
            self.object_display_mode = DM_CONTRAST
        else:  # DM_CONTRAST or any other mode
            self.object_display_mode = DM_LOCATE
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

    def _mount_control_queue(self):
        if not self.config_object.get_option("mount_control", False):
            return None
        return self.command_queues.get("mountcontrol")

    def _current_pointing_radec(self):
        solution = self.shared_state.solution()
        if not solution or not solution.has_pointing():
            return None
        aligned = solution.pointing.aligned.estimate
        if aligned is None:
            return None
        return aligned.RA, aligned.Dec

    def key_number(self, number):
        """Handle Object Details numeric keys for optional INDI mount control."""
        mountcontrol_queue = self._mount_control_queue()
        if mountcontrol_queue is None:
            return

        if number == 0:
            mountcontrol_queue.put({"type": "stop_movement"})
            self.message(_("Mount Stop"), 1)
        elif number == 1:
            mountcontrol_queue.put({"type": "init"})
            pointing = self._current_pointing_radec()
            if pointing is not None:
                mountcontrol_queue.put(
                    {"type": "sync", "ra": pointing[0], "dec": pointing[1]}
                )
            self.message(_("Mount Init"), 1)
        elif number == 2:
            mountcontrol_queue.put({"type": "manual_movement", "direction": "south"})
        elif number == 3:
            mountcontrol_queue.put({"type": "reduce_step_size"})
        elif number == 4:
            mountcontrol_queue.put({"type": "manual_movement", "direction": "west"})
        elif number == 5:
            mountcontrol_queue.put(
                {
                    "type": "goto_target",
                    "ra": self.object.ra,
                    "dec": self.object.dec,
                }
            )
            self.message(_("Mount GoTo"), 1)
        elif number == 6:
            mountcontrol_queue.put({"type": "manual_movement", "direction": "east"})
        elif number == 7:
            pointing = self._current_pointing_radec()
            if pointing is None:
                self.message(_("No solve"), 1)
                return
            mountcontrol_queue.put({"type": "sync", "ra": pointing[0], "dec": pointing[1]})
            self.message(_("Mount Sync"), 1)
        elif number == 8:
            mountcontrol_queue.put({"type": "manual_movement", "direction": "north"})
        elif number == 9:
            mountcontrol_queue.put({"type": "increase_step_size"})
        else:
            logger.warning("Unhandled mount-control number key: %s", number)

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
        if not self.shared_state.solution().has_pointing():
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
            self.descTextLayout.previous()
            typeconst = self.texts.get("type-const")
            if typeconst and isinstance(typeconst, TextLayouter):
                typeconst.previous()
        else:
            self.change_fov(-1)

    def serialize_ui_state(self) -> dict:
        """
        Serialize the current state of the object details for inter-process communication
        """
        try:
            # Get display mode name
            display_modes = {
                DM_DESC: "description",
                DM_LOCATE: "locate",
                DM_POSS: "poss_image",
                DM_SDSS: "sdss_image",
            }

            # Serialize the object information safely
            object_info = {}
            if self.object:
                object_info = {
                    "display_name": getattr(
                        self.object, "display_name", str(self.object)
                    ),
                    "object_type": getattr(self.object, "obj_type", "Unknown"),
                    "catalog": getattr(self.object, "catalog", "Unknown"),
                    "sequence": getattr(self.object, "sequence", ""),
                    "ra": getattr(self.object, "ra", None),
                    "dec": getattr(self.object, "dec", None),
                    "magnitude": str(getattr(self.object, "magnitude", "Unknown")),
                    "size": str(getattr(self.object, "size", "Unknown")),
                    "const": getattr(self.object, "const", "Unknown"),
                }

            # Get observation count safely
            observation_count = 0
            try:
                if hasattr(self, "observations_db") and self.object:
                    observation_count = (
                        self.observations_db.get_observation_count(
                            self.object.catalog, self.object.sequence
                        )
                        if hasattr(self.object, "catalog")
                        and hasattr(self.object, "sequence")
                        else 0
                    )
            except Exception:
                observation_count = 0

            # Get pointing instructions based on mount type
            pointing_info = {}
            try:
                if self.object:
                    point_val1, point_val2 = calc_utils.aim_degrees(
                        self.shared_state,
                        self.mount_type,
                        self.screen_direction,
                        self.object,
                    )

                    if point_val1 is not None and point_val2 is not None:
                        if self.mount_type == "Alt/Az":
                            pointing_info = {
                                "point_az": round(point_val1, 2),
                                "point_alt": round(point_val2, 2),
                                "mount_type": "Alt/Az",
                            }
                        else:  # EQ Mount
                            pointing_info = {
                                "point_ra": round(point_val1, 2),
                                "point_dec": round(point_val2, 2),
                                "mount_type": "EQ",
                            }
            except Exception:
                pointing_info = {"error": "Could not calculate pointing instructions"}

            return {
                "object": object_info,
                "display_mode": display_modes.get(self.object_display_mode, "unknown"),
                "object_list_length": len(self.object_list) if self.object_list else 0,
                "observation_count": observation_count,
                "has_image": self.object_image is not None,
                "screen_direction": self.screen_direction,
                "mount_type": self.mount_type,
                "pointing": pointing_info,
            }
        except Exception as e:
            return {"error": f"Failed to serialize object details state: {str(e)}"}
