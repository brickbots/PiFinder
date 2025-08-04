from PiFinder.ui.base import UIModule
from PiFinder.state_utils import sleep_for_framerate
from PiFinder.ui.marking_menus import MarkingMenu, MarkingMenuOption
from PiFinder.ui.textentry import UITextEntry
from PiFinder import config

class UIsqm(UIModule):
    """
    Displays current SQM value and provides entry to manually set SQM value
    """
    __title__ = "SQM"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.menu_index = 0
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            right=MarkingMenuOption(),
            down=MarkingMenuOption(),
        )

    def update(self, force=False):
        sleep_for_framerate(self.shared_state)
        self.clear_screen()
        sqm_value = self.shared_state.get_sky_brightness()
        self.draw.text((10, 20), f"Current SQM: {sqm_value}", font=self.fonts.large.font, fill=self.colors.get(128))
        if sqm_value is not None:
            self.draw.text((10, 40), f"    {sqm_value}", font=self.fonts.large.font, fill=self.colors.get(128))
        else:
            self.draw.text((10, 40), "No SQM value set", font=self.fonts.small.font, fill=self.colors.get(128))

        self.draw.text(
            (10, 80),
            _("Manually..."),
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )
        if self.menu_index == 0:
            self.draw_menu_pointer(80)

    def key_down(self):
        self.menu_index += 1
        if self.menu_index > 1:
            self.menu_index = 1

    def key_up(self):
        self.menu_index -= 1
        if self.menu_index < 0:
            self.menu_index = 0

    def key_right(self):
        if self.menu_index == 0:
            self.jump_to_label("set_sqm")

    def draw_menu_pointer(self, horiz_position: int):
        self.draw.text(
            (2, horiz_position),
            self._RIGHT_ARROW,
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )

    def active(self):
        """
        Called when a module becomes active
        i.e. foreground controlling display
        """
