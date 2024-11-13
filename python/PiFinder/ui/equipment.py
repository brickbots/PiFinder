import time

from luma.core.device import sleep

from PiFinder.ui.base import UIModule
from PiFinder import utils
from PiFinder.state_utils import sleep_for_framerate
from PiFinder.ui.ui_utils import TextLayouter, SpaceCalculatorFixed
from PiFinder import config
sys_utils = utils.get_sys_utils()


class UIEquipment(UIModule):
    """
    Displays various status information
    """

    __title__ = "Equipment"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def update(self, force=False):
        sleep_for_framerate(self.shared_state)
        cfg = config.Config()
        self.clear_screen()

        if cfg.equipment.active_telescope is None:
            self.draw.text(
                (10, 30),
                "No telescope selected",
                font=self.fonts.small.font,
                fill=self.colors.get(128),
            )
        else:
            self.draw.text(
                (10, 30),
                (cfg.equipment.active_telescope.make + " " + cfg.equipment.active_telescope.name).strip(),
                font=self.fonts.small.font,
                fill=self.colors.get(128),
            )

        if cfg.equipment.active_eyepiece is None:
            self.draw.text(
                (10, 50),
                "No eyepiece selected",
                font=self.fonts.small.font,
                fill=self.colors.get(128),
            )
        else:
            self.draw.text(
                (10, 50),
                (cfg.equipment.active_eyepiece.make + " " + cfg.equipment.active_eyepiece.name).strip(),
                font=self.fonts.small.font,
                fill=self.colors.get(128),
            )

        if cfg.equipment.active_telescope is not None and cfg.equipment.active_eyepiece is not None:
            mag = cfg.equipment.calc_magnification()
            if mag > 0:
                self.draw.text(
                    (10, 70),
                    f"Mag: {mag:.0f}x",
                    font=self.fonts.base.font,
                    fill=self.colors.get(128),
                )

                tfov = cfg.equipment.calc_tfov()
                tfov_degrees = int(tfov)
                tfov_minutes = int((tfov - tfov_degrees) * 60)
                self.draw.text(
                    (10, 90),
                    f"TFOV: {tfov_degrees:.0f}°{tfov_minutes:02.0f}'",
                    font=self.fonts.base.font,
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
