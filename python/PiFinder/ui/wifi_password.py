
import logging
from PiFinder import state_utils
from PiFinder.ui.base import UIModule
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu

logger = logging.getLogger("WiFiPassword")


class UIGPSStatus(UIModule):
    """
    UI for seeing GPS status
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def update(self, force=False):
        state_utils.sleep_for_framerate(self.shared_state)
        self.clear_screen()
        draw_pos = self.display_class.titlebar_height + 2

        # Status message
        self.draw.text(
            (0, draw_pos),
            "SSID:",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        draw_pos += 16
        self.draw.text(
            (0, draw_pos),
            "1234567890123457890123456789012",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        return self.screen_update()
