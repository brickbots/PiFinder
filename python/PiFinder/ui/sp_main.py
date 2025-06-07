#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
StarParty main menu

Either shows group info + leave
or
Create/Join
"""

from random import choice
from StarParty.sp_usernames import sp_usernames
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.ui.text_menu import UITextMenu


class UISPMain(UITextMenu):
    """
    Star Party Main menu
    """

    __help_name__ = "starparty"
    __title__ = "StarParty"
    _STAR = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._menu_vertical_offset = 20

        # Marking Menu - Just default help for now
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            right=MarkingMenuOption(),
            down=MarkingMenuOption(),
        )

        self.sp_username = self.config_object.get_option(
            "sp_username", choice(sp_usernames)
        )

    async def update_custom(self) -> None:
        self.draw.text(
            (0, 20),
            f"{self.sp_username:^15}",
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        return

    def set_menu(
        self, menu_items: dict, current_index: int = 0, menu_type: str = "single"
    ) -> None:
        """
        Reset menu items
        """
        self._current_item_index = current_index
        self.item_definition["items"] = menu_items
        self._menu_items = [x["name"] for x in self.item_definition["items"]]
        self._menu_type = menu_type

    def mode_disconnected(self) -> None:
        """
        Set mode to disconnected
        """

        self.set_menu(
            [
                {
                    "name": _("Connect"),
                    "value": "connect",
                },
                {
                    "name": _("Username"),
                    "value": "username",
                },
            ]
        )

    def mode_connected(self) -> None:
        """
        Set mode to connected
        Change menu items
        """

        self.set_menu(
            [
                {
                    "name": _("Join Group"),
                    "value": "join_groups",
                },
                {
                    "name": _("Add Group"),
                    "value": "add_group",
                },
                {
                    "name": _("Disconnect"),
                    "value": "disconnect",
                },
            ]
        )

    async def key_right(self):
        selected_item = self._menu_items[self._current_item_index]
        selected_item_definition = self.get_item(selected_item)

        if selected_item_definition["value"] == "disconnect":
            if self.sp_client_object.connected:
                await self.sp_client_object.disconnect()
                self.mode_disconnected()
            else:
                print("Not connected")
            return

        if selected_item_definition["value"] == "connect":
            print("SP - CONNECTING")
            await self.sp_client_object.connect(
                host="spserver.local", username=self.sp_username
            )
            print("SP - CONNECTED")
            self.mode_connected()
            return
