#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module holds some callbacks
used by the menu system

Each one takes the current ui module as an argument

"""

import logging
import gettext

from typing import Any, TYPE_CHECKING
from PiFinder import utils
from PiFinder.ui.base import UIModule
from PiFinder.catalogs import CatalogFilter

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


sys_utils = utils.get_sys_utils()


logger = logging.getLogger("UI.Callbacks")


def go_back(ui_module: UIModule) -> None:
    """
    Just removes the current ui module fom the stack
    """
    ui_module.remove_from_stack()
    return


def reset_filters(ui_module: UIModule) -> None:
    """
    Reset all filters to default
    """
    ui_module.config_object.reset_filters()

    new_filter = CatalogFilter(shared_state=ui_module.shared_state)
    new_filter.load_from_config(ui_module.config_object)

    ui_module.catalogs.set_catalog_filter(new_filter)
    ui_module.catalogs.filter_catalogs()
    ui_module.message(_("Filters Reset"))
    ui_module.remove_from_stack()
    return


def activate_debug(ui_module: UIModule) -> None:
    """
    Sets camera into debug
    add fake gps info
    """
    ui_module.command_queues["camera"].put("debug")
    ui_module.command_queues["console"].put("Test Mode Activated")
    ui_module.command_queues["ui_queue"].put("test_mode")
    ui_module.message(_("Test Mode"))


def set_exposure(ui_module: UIModule) -> None:
    """
    Sets exposure to current value in config option
    """
    new_exposure: int = ui_module.config_object.get_option("camera_exp")
    logger.info("Set exposure %f", new_exposure)
    ui_module.command_queues["camera"].put(f"set_exp:{new_exposure}")


def shutdown(ui_module: UIModule) -> None:
    """
    shuts down the Pi
    """
    ui_module.message(_("Shutting Down"), 10)
    sys_utils.shutdown()


def restart_pifinder(ui_module: UIModule) -> None:
    """
    Uses systemctl to restart the PiFinder
    service
    """
    ui_module.message(_("Restarting..."), 2)
    sys_utils.restart_pifinder()


def restart_system(ui_module: UIModule) -> None:
    """
    Restarts the system
    """
    ui_module.message(_("Restarting..."), 2)
    sys_utils.restart_system()


def switch_cam_imx477(ui_module: UIModule) -> None:
    ui_module.message(_("Switching cam"), 2)
    sys_utils.switch_cam_imx477()
    restart_system(ui_module)


def switch_cam_imx296(ui_module: UIModule) -> None:
    ui_module.message(_("Switching cam"), 2)
    sys_utils.switch_cam_imx296()
    restart_system(ui_module)


def switch_cam_imx462(ui_module: UIModule) -> None:
    ui_module.message(_("Switching cam"), 2)
    sys_utils.switch_cam_imx462()
    restart_system(ui_module)


def get_camera_type(ui_module: UIModule) -> list[str]:
    cam_id = "000"

    # read config.txt into a list
    with open("/boot/config.txt", "r") as boot_in:
        boot_lines = list(boot_in)

    # Look for the line without a comment...
    for line in boot_lines:
        if line.startswith("dtoverlay=imx"):
            cam_id = line[10:16]
            # imx462 uses imx290 driver
            if cam_id == "imx290":
                cam_id = "imx462"

    return [cam_id]


def switch_language(ui_module: UIModule) -> None:
    iso2_code = ui_module.config_object.get_option("language")
    msg = str(f"Language: {iso2_code}")
    ui_module.message(_(msg))
    lang = gettext.translation(
        "messages", "locale", languages=[iso2_code], fallback=(iso2_code == "en")
    )
    lang.install()
    logger.info("Switch Language: %s", iso2_code)


def go_wifi_ap(ui_module: UIModule) -> None:
    ui_module.message(_("WiFi to AP"), 2)
    sys_utils.go_wifi_ap()
    restart_system(ui_module)


def go_wifi_cli(ui_module: UIModule) -> None:
    ui_module.message(_("WiFi to Client"), 2)
    sys_utils.go_wifi_cli()
    restart_system(ui_module)


def get_wifi_mode(ui_module: UIModule) -> list[str]:
    wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
    with open(wifi_txt, "r") as wfs:
        return [wfs.read()]

def gps_reset(ui_module: UIModule) -> None:
    ui_module.command_queues["gps"].put(("reset", {}))
    ui_module.message("Location Reset", 2)
    
def set_time(ui_module: UIModule, time_str: str) -> None:
    """
    Sets the time from the time entry UI
    """
    logger.info(f"Setting time to: {time_str}")
    from datetime import datetime
    import pytz

    timezone_str = ui_module.shared_state.location().timezone

    # First create a datetime object (using today's date by default)
    dt = datetime.strptime(time_str, "%H:%M:%S")

    # Get the timezone object
    timezone = pytz.timezone(timezone_str)

    # Create a timezone-aware datetime by combining today's date with the time
    # and localizing it to the specified timezone
    now = datetime.now()
    dt_with_date = datetime(now.year, now.month, now.day, 
                            dt.hour, dt.minute, dt.second)
    dt_with_timezone = timezone.localize(dt_with_date)

    ui_module.command_queues["gps"].put(("time", {"time": dt_with_timezone}))
    ui_module.message(_("Time: {time}").format(time=time_str), 2)