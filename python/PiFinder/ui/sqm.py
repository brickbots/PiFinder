import time

from luma.core.device import sleep

from PiFinder.ui.base import UIModule
from PiFinder import utils
from PiFinder.state_utils import sleep_for_framerate
from PiFinder.ui.ui_utils import TextLayouter, SpaceCalculatorFixed
sys_utils = utils.get_sys_utils()


class UISQM(UIModule):
    """
    Displays various status information
    """

    __title__ = "SQM"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def update(self, force=False):
        sleep_for_framerate(self.shared_state)
        self.clear_screen()

        if (self.shared_state.solve_state is None or self.shared_state.solution() is None or self.shared_state.solution()["SQM"] is None):
            self.draw.text(
                (10, 30),
                "NO SQM DATA",
                font=self.fonts.bold.font,
                fill=self.colors.get(128),
            )
        else:
            self.draw.text(
                (10, 30),
                f"{self.shared_state.solution()['SQM'][0]:.2f}",
                font=self.fonts.huge.font,
                fill=self.colors.get(128),
            )
        return self.screen_update()

    # def key_up(self):
    #     self.text_layout.previous()
    #
    # def key_down(self):
    #     self.text_layout.next()

    def active(self):
        """
        Called when a module becomes active
        i.e. foreground controlling display
        """
