
import logging
from PiFinder import state_utils
from PiFinder.ui.base import UIModule
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.utils import get_sys_utils
# from PiFinder.sys_utils import Network

logger = logging.getLogger("WiFiPassword")


class UIWiFiPassword(UIModule):
    """
    UI for seeing GPS status
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def update(self, force=False):
        state_utils.sleep_for_framerate(self.shared_state)
        self.clear_screen()
        draw_pos = self.display_class.titlebar_height + 2

        net: Network = get_sys_utils().Network()
        mode = net.wifi_mode()
        if mode == "Client" or mode == "UNKN":
            # Mode
            self.draw.text(
                (0, draw_pos),
                f"Note: {mode} mode!",
                font=self.fonts.base.font,
                fill=self.colors.get(255),
            )
            draw_pos += 16
        elif mode == "Access Point":
            pass
        else:
            raise Exception(f"unexpected wifi mode: {mode}")

        ap_name = net.get_ap_name()
        ap_pwd = net.get_ap_pwd()
        self.draw.text(
            (0, draw_pos),
            "SSID:",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        self.draw.text(
            (30, draw_pos-2),
            ap_name,
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
        for ch in ap_pwd: 
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
            
        return self.screen_update()
