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

        self.menu_index = 0  # Observability

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

    async def update(self, force=True):
        # Clear Screen
        self.clear_screen()

        horiz_pos = self.display_class.titlebar_height

        if self.sp_client_object.connected:
            menu_text = _("Disconnect")
        else:
            menu_text = _("Connect")

        self.draw.text(
            (10, horiz_pos),
            menu_text,
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        if self.menu_index == 0:
            self.draw_menu_pointer(horiz_pos)
        horiz_pos += 18

    def draw_menu_pointer(self, horiz_position: int):
        self.draw.text(
            (2, horiz_position),
            self._RIGHT_ARROW,
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )

    async def key_right(self):
        if self.menu_index == 0:
            if self.sp_client_object.connected:
                await self.sp_client_object.disconnect()
            else:
                print("SP - CONNECTING")
                await self.sp_client_object.connect(
                    host="spserver.local", username="brickbots"
                )
                print("SP - CONNECTED")
            return

    def cycle_display_mode(self):
        """
        Cycle through available display modes
        for a module.  Invoked when the square
        key is pressed
        """
        pass

    async def key_down(self):
        self.menu_index += 1
        if self.menu_index > 4:
            self.menu_index = 4

    async def key_up(self):
        self.menu_index -= 1
        if self.menu_index < 0:
            self.menu_index = 0
