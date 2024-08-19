#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains all the UI Module classes

"""

from PiFinder import cat_images
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.ui.base import UIModule

from PiFinder.db.observations_db import ObservationsDatabase


# Constants for display modes
DM_DESC = 0  # Display mode for description
DM_LOCATE = 1  # Display mode for LOCATE
DM_POSS = 2  # Display mode for POSS
DM_SDSS = 3  # Display mode for SDSS


class UILog(UIModule):
    """
    Logging!
    """

    __help_name__ = "log"
    __title__ = "LOG"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.object = self.item_definition["object"]

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

    def update(self, force=True):
        # Clear Screen
        self.clear_screen()

        # paste image
        self.screen.paste(self.object_image)

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

        # Target Name
        self.draw.text(
            (0, 20),
            self.object.display_name,
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )

        # ID Line in BOld
        # Type / Constellation
        object_type = OBJ_TYPES.get(self.object.obj_type, self.object.obj_type)
        object_text = f"{object_type: <14} {self.object.const}"
        self.draw.text(
            (0, 36), object_text, font=self.fonts.bold.font, fill=self.colors.get(255)
        )

        return self.screen_update()

    def cycle_display_mode(self):
        """
        Cycle through available display modes
        for a module.  Invoked when the square
        key is pressed
        """
        pass

    def key_down(self):
        pass

    def key_up(self):
        pass
