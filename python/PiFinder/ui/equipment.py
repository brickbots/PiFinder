from PiFinder.ui.base import UIModule
from PiFinder import utils
from PiFinder.state_utils import sleep_for_framerate
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.ui.text_menu import UITextMenu
from PiFinder import config

sys_utils = utils.get_sys_utils()


class UIEquipment(UIModule):
    """
    Displays various status information
    """

    __title__ = "Equipment"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.menu_index = 0  # Telescope
        # Marking Menu - Just default help for now
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            right=MarkingMenuOption(),
            down=MarkingMenuOption(),
        )

        cfg = config.Config()

        eyepieces = cfg.equipment.eyepieces
        # Loop over eyepieces
        eyepiece_menu_items = []
        cnt = 0
        for eyepiece in eyepieces:
            eyepiece_menu_items.append(
                {
                    "name": eyepiece.name,
                    "value": cnt,
                }
            )
            cnt += 1

        self.eyepiece_menu = {
            "name": "Eyepiece",
            "class": UITextMenu,
            "select": "single",
            "config_option": "session.log_eyepiece",
            "items": eyepiece_menu_items,
        }

        telescopes = cfg.equipment.telescopes
        # Loop over telescopes
        telescope_menu_items = []
        cnt = 0
        for telescope in telescopes:
            telescope_menu_items.append(
                {
                    "name": telescope.name,
                    "value": cnt,
                }
            )
            cnt += 1

        self.telescope_menu = {
            "name": "Telescope",
            "class": UITextMenu,
            "select": "single",
            "config_option": "session.log_telescope",
            "items": telescope_menu_items,
        }

    def update(self, force=False):
        sleep_for_framerate(self.shared_state)
        cfg = config.Config()
        self.clear_screen()

        selected_eyepiece = self.config_object.get_option("session.log_eyepiece", "")
        selected_telescope = self.config_object.get_option("session.log_telescope", "")

        if selected_eyepiece != "":
            cfg.equipment.set_active_eyepiece(
                cfg.equipment.eyepieces[selected_eyepiece]
            )
            cfg.save_equipment()
            self.config_object.set_option("session.log_eyepiece", "")

        if selected_telescope != "":
            cfg.equipment.set_active_telescope(
                cfg.equipment.telescopes[selected_telescope]
            )
            cfg.save_equipment()
            self.config_object.set_option("session.log_telescope", "")

        if cfg.equipment.active_telescope is None:
            self.draw.text(
                (10, 20),
                "No telescope selected",
                font=self.fonts.small.font,
                fill=self.colors.get(128),
            )
        else:
            self.draw.text(
                (10, 20),
                cfg.equipment.active_telescope.name.strip(),
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )

        if cfg.equipment.active_eyepiece is None:
            self.draw.text(
                (10, 35),
                "No eyepiece selected",
                font=self.fonts.small.font,
                fill=self.colors.get(128),
            )
        else:
            self.draw.text(
                (10, 35),
                cfg.equipment.active_eyepiece.name.strip(),
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )

        if (
            cfg.equipment.active_telescope is not None
            and cfg.equipment.active_eyepiece is not None
        ):
            mag = cfg.equipment.calc_magnification()
            if mag > 0:
                self.draw.text(
                    (10, 50),
                    f"Mag: {mag:.0f}x",
                    font=self.fonts.base.font,
                    fill=self.colors.get(128),
                )

                tfov = cfg.equipment.calc_tfov()
                tfov_degrees = int(tfov)
                tfov_minutes = int((tfov - tfov_degrees) * 60)
                self.draw.text(
                    (10, 70),
                    f"TFOV: {tfov_degrees:.0f}°{tfov_minutes:02.0f}'",
                    font=self.fonts.base.font,
                    fill=self.colors.get(128),
                )

        horiz_pos = self.display_class.titlebar_height + 70

        self.draw.text(
            (10, horiz_pos),
            "Telescope...",
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )
        if self.menu_index == 0:
            self.draw_menu_pointer(horiz_pos)

        horiz_pos += 18

        self.draw.text(
            (10, horiz_pos),
            "Eyepiece...",
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )
        if self.menu_index == 1:
            self.draw_menu_pointer(horiz_pos)

        return self.screen_update()

    def key_down(self):
        self.menu_index += 1
        if self.menu_index > 4:
            self.menu_index = 4

    def key_up(self):
        self.menu_index -= 1
        if self.menu_index < 0:
            self.menu_index = 0

    def key_right(self):
        if self.menu_index == 0:
            self.add_to_stack(self.telescope_menu)
        if self.menu_index == 1:
            self.add_to_stack(self.eyepiece_menu)

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
