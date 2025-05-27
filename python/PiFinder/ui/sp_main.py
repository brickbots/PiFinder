#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
StarParty main menu

Either shows group info + leave
or
Create/Join
"""

from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.ui.base import UIModule
from PiFinder.ui.text_menu import UITextMenu


class UISPMain(UIModule):
    """
    Star Party Main menu
    """

    __help_name__ = "starparty"
    __title__ = "StarParty"
    _STAR = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Marking Menu - Just default help for now
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            right=MarkingMenuOption(),
            down=MarkingMenuOption(),
        )

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

    def update(self, force=True):
        # Clear Screen
        self.clear_screen()

        horiz_pos = self.display_class.titlebar_height

        #
        self.draw.text(
            (10, horiz_pos),
            _("StarParty"),
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        if self.menu_index == 0:
            self.draw_menu_pointer(horiz_pos)
        horiz_pos += 18

        # Observability
        self.draw.text(
            (10, horiz_pos),
            _("Observability"),
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )
        if self.menu_index == 1:
            self.draw_menu_pointer(horiz_pos)
        horiz_pos += 14

    def draw_menu_pointer(self, horiz_position: int):
        self.draw.text(
            (2, horiz_position),
            self._RIGHT_ARROW,
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )

    def key_right(self):
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
