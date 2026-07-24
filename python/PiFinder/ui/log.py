#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains all the UI Module classes

"""

from PiFinder import obslog
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.ui.base import UIModule
from PiFinder.ui.text_menu import UITextMenu

from PiFinder.db.observations_db import ObservationsDatabase


class UILog(UIModule):
    """
    Logging!
    """

    __help_name__ = "log"
    __title__ = "LOG"
    _STAR = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.object = self.item_definition["object"]
        self.title = self.object.display_name

        self.fov_list = [1, 0.5, 0.25, 0.125]
        self.fov_index = 0

        # Marking Menu - Just default help for now
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            right=MarkingMenuOption(),
            down=MarkingMenuOption(),
        )

        # Used for displaying obsevation counts
        self.observations_db = ObservationsDatabase()

        self.menu_index = 1  # Observability

        # conditions and eyepiece menus
        self.conditions_menu = {
            "name": _("Conditions"),
            "class": UITextMenu,
            "select": "single",
            "items": [
                {
                    "name": _("Transparency"),
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "session.log_transparency",
                    "items": [
                        {
                            # TRANSLATORS: Transparency not available
                            "name": _("NA"),
                            "value": "NA",
                        },
                        {
                            "name": _("Excellent"),
                            "value": "Excellent",
                        },
                        {
                            "name": _("Very Good"),
                            "value": "Very Good",
                        },
                        {
                            "name": _("Good"),
                            "value": "Good",
                        },
                        {
                            "name": _("Fair"),
                            "value": "Fair",
                        },
                        {
                            "name": _("Poor"),
                            "value": "Poor",
                        },
                    ],
                },
                {
                    "name": _("Seeing"),
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "session.log_seeing",
                    "items": [
                        {
                            # TRANSLATORS: Seeing not available
                            "name": _("NA"),
                            "value": "NA",
                        },
                        {
                            "name": _("Excellent"),
                            "value": "Excellent",
                        },
                        {
                            "name": _("Very Good"),
                            "value": "Very Good",
                        },
                        {
                            "name": _("Good"),
                            "value": "Good",
                        },
                        {
                            "name": _("Fair"),
                            "value": "Fair",
                        },
                        {
                            "name": _("Poor"),
                            "value": "Poor",
                        },
                    ],
                },
            ],
        }

        self.reset_config()

    def draw_stars(self, horiz_pos, star_count):
        # Star pitch / left margin derive from the star glyph width so the five
        # stars spread with the display instead of bunching on the left.
        star_pitch = self.fonts.large.width + 6
        star_x0 = round(self.display_class.resX * 20 / 128)
        for i in range(5):
            star_color = 64
            if star_count > i:
                star_color = 255
            self.draw.text(
                (star_x0 + i * star_pitch, horiz_pos),
                self._STAR,
                font=self.fonts.large.font,
                fill=self.colors.get(star_color),
            )

    def reset_config(self):
        """
        Set log entries to default
        """
        # Log note entries
        self.log_observability = 0
        self.log_appeal = 0

    def update(self, force=True):
        # Clear Screen
        self.clear_screen()

        # dim image
        self.draw.rectangle(
            [
                0,
                0,
                self.display_class.resX,
                self.display_class.resY,
            ],
            fill=(0, 0, 0, 100),
        )

        if not self.shared_state.solve_state():
            self.draw.text(
                (0, self.display_class.titlebar_height + 3),
                _("No Solve Yet"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return self.screen_update()

        horiz_pos = self.display_class.titlebar_height
        # Row advances derived from the large-font height: item->item is a touch
        # over the glyph height; label->its-stars and stars->next-label are a
        # touch under (reproduces the 128 panel's 18 / 14 / 11-15 cadence).
        label_gap = self.fonts.large.height + 2
        to_stars = self.fonts.large.height - 2
        from_stars = self.fonts.large.height - 2

        # Target Name
        self.draw.text(
            (10, horiz_pos),
            _("SAVE Log"),
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        if self.menu_index == 0:
            self.draw_menu_pointer(horiz_pos)
        horiz_pos += label_gap

        # Observability
        self.draw.text(
            (10, horiz_pos),
            _("Observability"),
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )
        if self.menu_index == 1:
            self.draw_menu_pointer(horiz_pos)
        horiz_pos += to_stars
        self.draw_stars(horiz_pos, self.log_observability)
        horiz_pos += from_stars

        # Appeal
        self.draw.text(
            (10, horiz_pos),
            _("Appeal"),
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )
        if self.menu_index == 2:
            self.draw_menu_pointer(horiz_pos)
        horiz_pos += to_stars
        self.draw_stars(horiz_pos, self.log_appeal)
        horiz_pos += from_stars

        self.draw.text(
            (10, horiz_pos),
            _("Conditions..."),
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )
        if self.menu_index == 3:
            self.draw_menu_pointer(horiz_pos)
        horiz_pos += label_gap

        self.draw.text(
            (10, horiz_pos),
            _("Eyepiece..."),
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )
        if self.menu_index == 4:
            self.draw_menu_pointer(horiz_pos)

        return self.screen_update()

    def draw_menu_pointer(self, horiz_position: int):
        self.draw.text(
            (2, horiz_position),
            self._RIGHT_ARROW,
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )

    def record_object(self):
        """
        Creates a session if needed
        then records the current target

        _object should be a target like CompositeObject

        These will be jsonified when logging
        """
        # build notes
        log_eyepiece = self.config_object.equipment.active_eyepiece
        if log_eyepiece is None:
            # TRANSLATORS: eyepiece info not available
            log_eyepiece = _("NA")
        else:
            log_eyepiece = f"{log_eyepiece.focal_length_mm}mm {log_eyepiece.name}"

        notes = {
            "schema_ver": 2,
            "transparency": self.config_object.get_option(
                "session.log_transparency", "NA"
            ),
            "seeing": self.config_object.get_option("session.log_seeing", "NA"),
            "eyepiece": log_eyepiece,
            "observability": self.log_observability,
            "appeal": self.log_appeal,
        }
        self._observing_session = obslog.Observation_session(
            self.shared_state, self.__uuid__
        )

        self._observing_session.log_object(
            catalog=self.object.catalog_code,
            sequence=self.object.sequence,
            solution=self.shared_state.solution(),
            notes=notes,
        )
        self.catalogs.mark_logged(self.object)
        self.reset_config()

    def key_number(self, number: int):
        """
        Shortcut for stars
        """
        if number <= 5:
            if self.menu_index == 1:
                self.log_observability = number

            if self.menu_index == 2:
                self.log_appeal = number

    def key_right(self):
        """
        Log the logging
        """
        if self.menu_index == 0:
            self.record_object()
            self.message(_("Logged!"))
            self.remove_from_stack()
            return

        if self.menu_index == 1:
            self.log_observability += 1
            if self.log_observability > 5:
                self.log_observability = 0

        if self.menu_index == 2:
            self.log_appeal += 1
            if self.log_appeal > 5:
                self.log_appeal = 0

        if self.menu_index == 3:
            self.add_to_stack(self.conditions_menu)

        if self.menu_index == 4:
            self.jump_to_label("select_eyepiece")

    def cycle_display_mode(self):
        """
        Cycle through available display modes
        for a module.  Invoked when the square
        key is pressed
        """
        pass

    def key_down(self):
        self.menu_index += 1
        if self.menu_index > 4:
            self.menu_index = 4

    def key_up(self):
        self.menu_index -= 1
        if self.menu_index < 0:
            self.menu_index = 0
