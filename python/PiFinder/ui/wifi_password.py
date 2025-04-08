
import logging
from PiFinder import state_utils
from PiFinder.ui.base import UIModule
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.utils import get_sys_utils
# from PiFinder.sys_utils import Network

logger = logging.getLogger("WiFiPassword")

# Constants for Display Modes
DM_QR = 0    # Display QR code for scanning with smartphone or tablet. 
DM_PLAIN_PWD = 1 # Display plain password

class UIWiFiPassword(UIModule):
    """
    UI for displaying the Access Point name and password.
    """

    __help_name__ = "wifi_password"
    __title__ = "WIFI"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        net: Network = get_sys_utils().Network()
        self.ap_mode = net.wifi_mode()
        self.ap_name = net.get_ap_name()
        self.ap_pwd = net.get_ap_pwd()

        self.qr_image = None

        self.display_mode = DM_PLAIN_PWD

    def cycle_display_mode(self):
        """
        Cycle through available display modes
        for a module.  Invoked when the square
        key is pressed
        """
        self.display_mode = (
            self.display_mode + 1 if self.display_mode < 1 else 0
        )
        self.update()


    def update(self, force=False):
        state_utils.sleep_for_framerate(self.shared_state)
        self.clear_screen()
        draw_pos = self.display_class.titlebar_height + 2

        if self.display_mode == DM_PLAIN_PWD: 
            self._display_plain_pwd(draw_pos)
        else: 
            pass
            
        return self.screen_update()

    def _display_plain_pwd(self, draw_pos):
        if self.ap_mode == "Client" or self.ap_mode == "UNKN":
            # Mode
            self.draw.text(
                (0, draw_pos),
                f"Note: {self.ap_mode} mode!",
                font=self.fonts.base.font,
                fill=self.colors.get(255),
            )
            draw_pos += 16
        elif self.ap_mode == "Access Point":
            pass
        else:
            raise Exception(f"unexpected wifi mode: {self.ap_mode}")

        self.draw.text(
            (0, draw_pos),
            "SSID:",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        self.draw.text(
            (30, draw_pos-2),
            self.ap_name,
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        # Password
        draw_pos += 10
        self.draw.text(
            (0, draw_pos),
            "Password:",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 16
        dx = 8  # size of character
        dy = 16 # line height
        brk = 16 # max number of characters in line
        x = 0 # draw position
        i = 0 # character count in line
        for ch in self.ap_pwd: 
            if ch.isdigit(): 
                self.draw.text(
                    (x, draw_pos),
                    ch,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(128),
                )
            elif ch.islower():
                self.draw.text(
                    (x, draw_pos),
                    ch,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(225),
                )
            elif ch.isupper():
                self.draw.text(
                    (x, draw_pos),
                    ch,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )
            else: 
                self.draw.text(
                    (x, draw_pos),
                    ch,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(100),
                )

            x += dx
            i += 1
            if i >= brk:
                i = 0
                x = 0
                draw_pos += dy
