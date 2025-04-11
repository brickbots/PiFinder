import logging
import qrcode
import math

from PiFinder import state_utils
from PiFinder.ui.base import UIModule
from PiFinder.utils import get_sys_utils
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
# from PiFinder.sys_utils import Network

logger = logging.getLogger("WiFiPassword")

# Constants for Display Modes
DM_QR = 0  # Display QR code for scanning with smartphone or tablet.
DM_PLAIN_PWD = 1  # Display plain password
DM_LAST = DM_PLAIN_PWD


class UIWiFiPassword(UIModule):
    """
    UI for displaying the Access Point name and password.
    """

    __help_name__ = "wifi_password"
    __title__ = "WIFI"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.network = get_sys_utils().Network()
        self._update_info()

        self.qr_image = None

        self.wifi_display_mode = DM_QR

        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(
                label="QR", callback=self.mm_display_qr, enabled=True
            ),
            right=MarkingMenuOption(
                label="Passwd", callback=self.mm_display_pwd, enabled=True
            ),
            down=MarkingMenuOption(
                label="Mode", callback=self.mm_switch_mode, enabled=True
            ),
        )

    def mm_display_qr(self, marking_menu, menu_item):
        """
        Marking menu option to display the QR code
        """
        self.wifi_display_mode = DM_QR
        self._update_info()
        self.update()
        # logger.debug(f"Marking menu: {self.marking_menu}")
        return True

    def mm_display_pwd(self, marking_menu, menu_item):
        """
        Marking menu option to display the plain password
        """
        self.wifi_display_mode = DM_PLAIN_PWD
        self._update_info()
        self.update()
        # logger.debug(f"Marking menu: {self.marking_menu}")
        return True

    def mm_switch_mode(self, marking_menu, menu_item):
        self.jump_to_label("WiFi Mode")
        return False

    def _update_info(self):
        self.ap_mode = self.network.wifi_mode()
        self.ap_name = self.network.get_ap_name()
        self.ap_pwd = self.network.get_ap_pwd()
        self.wifi_qr = self._generate_wifi_qrcode(self.ap_name, self.ap_pwd, "WPA")
        self.wifi_qr_scaled = False

    def cycle_display_mode(self):
        """
        Cycle through available display modes
        for a module.  Invoked when the square
        key is pressed
        """
        self.wifi_display_mode = (
            self.wifi_display_mode + 1 if self.wifi_display_mode < DM_LAST else 0
        )
        self._update_info()
        self.update()

    def _generate_wifi_qrcode(self, ssid: str, password: str, security_type: str):
        wifi_data = f"WIFI:S:{ssid};T:{security_type};P:{password};H:false;"
        # logger.debug(f"WIFI Data: '{wifi_data}'")

        qr = qrcode.QRCode(
            version=1,  # 21x21 matrix
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,  # Size of a box of the
            border=1,
        )
        qr.add_data(wifi_data)
        qr.make(fit=True)

        qr_code_image = qr.make_image(
            # fill_color="red", back_color="black"
            fill_color="red",
            back_color="black",
        )
        # logger.warning(f"Generating WiFi QR Code: {qr_code_image.size[0]}, {qr_code_image.size[1]}")
        # qr_code_image.save("WiFi_QR_code.png", "PNG")

        return qr_code_image

    def update(self, force=False):
        state_utils.sleep_for_framerate(self.shared_state)
        self.clear_screen()
        draw_pos = self.display_class.titlebar_height + 2

        if self.wifi_display_mode == DM_PLAIN_PWD:
            self._display_plain_pwd(draw_pos)
        else:
            self._display_wifi_qr(draw_pos)

        return self.screen_update()

    def _display_wifi_qr(self, draw_pos: int) -> None:
        draw_pos = self.display_class.titlebar_height + 2
        draw_pos = self._show_ssid(draw_pos, True)

        if not self.wifi_qr_scaled:
            (width, height) = self.wifi_qr.size
            (target_width, target_height) = self.screen.size
            target_height -= draw_pos
            scale = min(target_width / width, target_height / height)
            self.wifi_qr = self.wifi_qr.resize(
                (math.floor(width * scale), math.floor(height * scale)), 1
            )  # Do antialiasing using LANCZOS (Can't find the constant)
            self.wifi_qr_scaled = True
            # logger.warning(f"WiFi QR Code scaled size: {math.floor(width*scale)}^²")
            # self.wifi_qr.save("WiFi_QR_Code_scaled.png", "PNG")

        self.screen.paste(self.wifi_qr, (0, draw_pos))
        pass

    def _display_plain_pwd(self, draw_pos: int) -> None:
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

        draw_pos = self._show_ssid(draw_pos)
        # Password
        self.draw.text(
            (0, draw_pos),
            "Password:",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 16
        dx = 8  # size of character
        dy = 16  # line height
        brk = 16  # max number of characters in line
        x = 0  # draw position
        i = 0  # character count in line
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

    def _show_ssid(self, draw_pos, truncate=False):
        self.draw.text(
            (0, draw_pos),
            "SSID:",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )

        # logger.debug(f"_show_ssid: {draw_pos}, {truncate}")
        x_pos = 30

        # If SSID is too long, display on separate line.
        if not truncate:
            if len(self.ap_name) > 14:
                draw_pos += 10
                x_pos = 0

        self.draw.text(
            (x_pos, draw_pos),
            self.ap_name,
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        draw_pos += 16
        return draw_pos
