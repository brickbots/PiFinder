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
from StarParty.sps_data import GroupActivity
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.ui.text_menu import UITextMenu


class UISPMain(UITextMenu):
    """
    Star Party Main menu
    """

    __help_name__ = "starparty"
    __title__ = "StarParty"
    _STAR = ""
    _GROUP_ACTIVITY_ICONS = {GroupActivity.HANG: "H", GroupActivity.RACE: "R"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._menu_vertical_offset = 20
        self._menu_horiz_offset = 3

        # Marking Menu - Just default help for now
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            right=MarkingMenuOption(),
            down=MarkingMenuOption(),
        )

        self.sp_username = self.config_object.get_option(
            "sp_username", choice(sp_usernames)
        )

        self.ui_mode = "disconnected"

    async def update_custom(self) -> None:
        if self.ui_mode in ["disconnected", "home"]:
            self.draw.text(
                (2, 20),
                f"{self.sp_username:^14}",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return

        if self.ui_mode == "join_group":
            if not self._menu_items:
                self.draw.text(
                    (2, 20),
                    f"{'No Groups':^14}",
                    font=self.fonts.large.font,
                    fill=self.colors.get(255),
                )
            return

        if self.ui_mode == "joined":
            self.draw.text(
                (2, 20),
                f"{self.sp_client_object.current_group.name:^14}",
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

    def mode_username(self) -> None:
        self._menu_vertical_offset = 0
        self.ui_mode = "username"
        self.set_menu(
            [
                {
                    "name": self.config_object.get_option(
                        "sp_username", choice(sp_usernames)
                    )
                },
                {"name": choice(sp_usernames)},
                {"name": choice(sp_usernames)},
                {"name": choice(sp_usernames)},
            ]
        )

    def mode_disconnected(self) -> None:
        """
        Set mode to disconnected
        """

        self._menu_vertical_offset = 20
        self.ui_mode = "disconnected"
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

    def mode_joined(self) -> None:
        """
        Set mode to joined
        In a group
        Change menu items
        """

        self._menu_vertical_offset = 20
        self.ui_mode = "joined"
        self.set_menu(
            [
                {
                    "name": _("Observers"),
                    "value": "list_observers",
                },
                {
                    "name": _("Leave Group"),
                    "value": "add_group",
                },
                {
                    "name": _("Disconnect"),
                    "value": "disconnect",
                },
            ]
        )

    def mode_home(self) -> None:
        """
        Set mode to home
        Connected, but no groups
        Change menu items
        """

        self._menu_vertical_offset = 20
        self.ui_mode = "home"
        self.set_menu(
            [
                {
                    "name": _("Join Group"),
                    "value": "join_group",
                },
                {
                    "name": _("Create Group"),
                    "value": "add_group",
                },
                {
                    "name": _("Disconnect"),
                    "value": "disconnect",
                },
            ]
        )

    async def mode_joingroup(self) -> None:
        """
        Set mode to Join Group
        Change menu items
        """

        self._menu_vertical_offset = 0
        self.ui_mode = "join_group"

        group_menu = []
        groups = await self.sp_client_object.list_groups()

        for group in groups:
            group_display = f"{self._GROUP_ACTIVITY_ICONS[group.activity]} {group.name} {group.observer_count}"
            group_menu.append({"name": group_display, "value": group.name})

        self.set_menu(group_menu)

    async def key_left(self):
        if self.ui_mode == "username":
            self.mode_disconnected()
            return

        if self.ui_mode == "join_group":
            self.mode_home()
            return

        # Return true is the default behavior here
        # This will pop this menu item off the stack
        return True

    async def key_right(self):
        selected_item = self._menu_items[self._current_item_index]
        selected_item_definition = self.get_item(selected_item)
        if self.ui_mode == "username":
            self.sp_username = selected_item
            self.mode_disconnected()
            return

        if self.ui_mode == "join_group":
            group_to_join = selected_item_definition["value"]
            await self.sp_client_object.join_group(group_to_join)
            self.mode_joined()

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
            self.mode_home()
            return

        if selected_item_definition["value"] == "username":
            self.mode_username()
            return

        if selected_item_definition["value"] == "join_group":
            await self.mode_joingroup()
            return
