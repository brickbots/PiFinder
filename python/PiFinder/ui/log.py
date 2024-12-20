#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains all the UI Module classes

"""

from PiFinder import cat_images
from PiFinder import obslog
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.ui.base import UIModule
from PiFinder.ui.text_menu import UITextMenu
from PiFinder import config

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

        solution = self.shared_state.solution()
        roll = 0
        if solution:
            roll = solution["Roll"]
        self.object_image = cat_images.get_display_image(
            self.object, "POSS", 1, roll, self.display_class, burn_in=False
        )

        self.menu_index = 1  # Observability

        # conditions and eyepiece menus
        self.conditions_menu = {
            "name": "Conditions",
            "class": UITextMenu,
            "select": "single",
            "items": [
                {
                    "name": "Transparency",
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "session.log_transparency",
                    "items": [
                        {
                            "name": "NA",
                            "value": "NA",
                        },
                        {
                            "name": "Excellent",
                            "value": "Excellent",
                        },
                        {
                            "name": "Very Good",
                            "value": "Very Good",
                        },
                        {
                            "name": "Good",
                            "value": "Good",
                        },
                        {
                            "name": "Fair",
                            "value": "Fair",
                        },
                        {
                            "name": "Poor",
                            "value": "Poor",
                        },
                    ],
                },
                {
                    "name": "Seeing",
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "session.log_seeing",
                    "items": [
                        {
                            "name": "NA",
                            "value": "NA",
                        },
                        {
                            "name": "Excellent",
                            "value": "Excellent",
                        },
                        {
                            "name": "Very Good",
                            "value": "Very Good",
                        },
                        {
                            "name": "Good",
                            "value": "Good",
                        },
                        {
                            "name": "Fair",
                            "value": "Fair",
                        },
                        {
                            "name": "Poor",
                            "value": "Poor",
                        },
                    ],
                },
            ],
        }

        cfg = config.Config()

        eyepieces_list = cfg.equipment.eyepieces

        # Loop over eyepieces and add to menu
        eyepiece_items = [
            {
                "name": "NA",
                "value": "NA",
            },
        ]
        for eyepiece in eyepieces_list:
            eyepiece_items.append(
                {
                    "name": eyepiece.name,

                    "value": (eyepiece.make + " " + eyepiece.name).lstrip(),
                }
            )

        self.eyepiece_menu = {
            "name": "Eyepiece",
            "class": UITextMenu,
            "select": "single",
            "config_option": "session.log_eyepiece",
            "items": eyepiece_items
        }

        self.reset_config()

    def draw_stars(self, horiz_pos, star_count):
        for i in range(5):
            star_color = 64
            if star_count > i:
                star_color = 255
            self.draw.text(
                (i * 15 + 20, horiz_pos),
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

        # paste image
        # self.screen.paste(self.object_image)

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
                (0, 20),
                "No Solve Yet",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return self.screen_update()

        horiz_pos = self.display_class.titlebar_height

        # Target Name
        self.draw.text(
            (10, horiz_pos),
            "SAVE Log",
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        if self.menu_index == 0:
            self.draw_menu_pointer(horiz_pos)
        horiz_pos += 18

        # Observability
        self.draw.text(
            (10, horiz_pos),
            "Observability",
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )
        if self.menu_index == 1:
            self.draw_menu_pointer(horiz_pos)
        horiz_pos += 14
        self.draw_stars(horiz_pos, self.log_observability)
        horiz_pos += 11

        # Appeal
        self.draw.text(
            (10, horiz_pos),
            "Appeal",
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )
        if self.menu_index == 2:
            self.draw_menu_pointer(horiz_pos)
        horiz_pos += 14
        self.draw_stars(horiz_pos, self.log_appeal)
        horiz_pos += 15

        self.draw.text(
            (10, horiz_pos),
            "Conditions...",
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )
        if self.menu_index == 3:
            self.draw_menu_pointer(horiz_pos)
        horiz_pos += 17

        self.draw.text(
            (10, horiz_pos),
            "Eyepiece...",
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
        notes = {
            "schema_ver": 2,
            "transparency": self.config_object.get_option(
                "session.log_transparency", "NA"
            ),
            "seeing": self.config_object.get_option("session.log_seeing", "NA"),
            "eyepiece": self.config_object.get_option("session.log_eyepiece", "NA"),
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
            self.message("Logged!")
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
            self.add_to_stack(self.eyepiece_menu)

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
