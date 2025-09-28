#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module holds some callbacks
used by the menu system

Each one takes the current ui module as an argument

"""

import logging
import gettext
import time

from typing import Any, TYPE_CHECKING
from PiFinder import utils, calc_utils
from PiFinder.ui.base import UIModule
from PiFinder.catalogs import CatalogFilter
from PiFinder.composite_object import CompositeObject, MagnitudeObject

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


def show_advanced_message(ui_module: UIModule) -> None:
    """
    Show popup message when entering Advanced settings menu
    """
    ui_module.message(_("Options for\nDIY PiFinders"), 2)
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
    from datetime import datetime
    import pytz

    logger.info(f"Setting time to: {time_str}")

    timezone_str = ui_module.shared_state.location().timezone

    # First create a datetime object (using today's date by default)
    dt = datetime.strptime(time_str, "%H:%M:%S")

    # Get the timezone object
    timezone = pytz.timezone(timezone_str)

    # Create a timezone-aware datetime by combining today's date with the time
    # and localizing it to the specified timezone
    now = datetime.now()
    dt_with_date = datetime(now.year, now.month, now.day, dt.hour, dt.minute, dt.second)
    dt_with_timezone = timezone.localize(dt_with_date)

    ui_module.command_queues["gps"].put(("time", {"time": dt_with_timezone}))
    ui_module.message(_("Time: {time}").format(time=time_str), 2)


def handle_radec_entry(ui_module: UIModule, ra_deg: float, dec_deg: float) -> None:
    """
    Handles RA/DEC coordinate entry from the coordinate input UI
    Creates a CompositeObject and adds it to recent list for navigation
    """
    from PiFinder.ui.object_details import UIObjectDetails

    logger.info(f"Received coordinates: RA={ra_deg:.6f}°, DEC={dec_deg:.6f}°")

    # Create a CompositeObject from the coordinates
    custom_object = create_custom_object_from_coords(ra_deg, dec_deg, ui_module)

    # Add to recent objects list for immediate navigation
    ui_module.shared_state.ui_state().add_recent(custom_object)

    # Show popup notification that user object was created
    ui_module.message(f"User object created\n{custom_object.display_name}", timeout=2)

    # Navigate to object details for the created object
    object_item_definition = {
        "name": custom_object.display_name,
        "class": UIObjectDetails,
        "object": custom_object,
        "object_list": [custom_object],  # Single object list
        "label": "object_details",
    }
    ui_module.add_to_stack(object_item_definition)

    logger.info(
        f"Created custom object: {custom_object.display_name} at RA={ra_deg:.6f}°, DEC={dec_deg:.6f}°"
    )


def create_custom_object_from_coords(
    ra_deg: float, dec_deg: float, ui_module: UIModule
):
    """
    Create a CompositeObject from RA/DEC coordinates
    """
    # Generate unique sequence number for custom objects
    # Use negative numbers to distinguish from regular catalog objects
    current_time_ms = int(time.time() * 1000)
    unique_id = -(current_time_ms % 1000000)  # Negative ID for custom objects

    # Generate automatic name and get the sequence number from it
    custom_name = generate_custom_object_name(ui_module)
    sequence_num = int(custom_name.split(" ")[1])  # Extract number from "CUSTOM X"

    # Determine constellation
    constellation = calc_utils.sf_utils.radec_to_constellation(ra_deg, dec_deg)

    # Generate description with coordinates in all supported formats
    description = generate_coordinate_description(ra_deg, dec_deg)

    # Create the CompositeObject following the pattern from pos_server.py
    custom_object = CompositeObject.from_dict(
        {
            "id": -1,
            "object_id": unique_id,
            "obj_type": "Custom",
            "ra": ra_deg,
            "dec": dec_deg,
            "const": constellation,
            "size": "",
            "mag": MagnitudeObject([]),
            "mag_str": "",
            "catalog_code": "USER",
            "sequence": sequence_num,
            "description": description,
            "names": [custom_name],
            "image_name": "",
            "logged": False,
        }
    )

    return custom_object


def generate_coordinate_description(ra_deg: float, dec_deg: float) -> str:
    """
    Generate a description with coordinates in all supported formats
    """
    # Convert RA from degrees to hours for HMS format
    ra_hours = ra_deg / 15.0

    # Format 1: HMS/DMS (Full format)
    ra_h, ra_m, ra_s = calc_utils.ra_to_hms(ra_deg)
    dec_d, dec_m, dec_s = calc_utils.dec_to_dms(dec_deg)
    dec_sign = "+" if dec_deg >= 0 else "-"
    hms_dms = f"RA: {ra_h:02d}:{ra_m:02d}:{ra_s:02d} DEC: {dec_sign}{abs(dec_d):02d}:{dec_m:02d}:{dec_s:02d}"

    # Format 2: Mixed (Hours/Degrees)
    mixed = f"RA: {ra_hours:.4f}h DEC: {dec_deg:+.4f}°"

    # Format 3: Decimal degrees
    decimal = f"RA: {ra_deg:.4f}° DEC: {dec_deg:+.4f}°"

    return f"User-defined coordinates\n\nHMS/DMS:\n{hms_dms}\n\nMixed:\n{mixed}\n\nDecimal:\n{decimal}"


def generate_custom_object_name(ui_module: UIModule) -> str:
    """
    Generate a unique name for custom objects (CUSTOM 1, CUSTOM 2, etc.)
    """
    # Get current recent list to check for existing custom objects
    recent_list = ui_module.shared_state.ui_state().recent_list()

    # Find highest existing CUSTOM number
    max_num = 0
    for obj in recent_list:
        if hasattr(obj, "catalog_code") and obj.catalog_code == "USER":
            for name in obj.names:
                if name.startswith("CUSTOM "):
                    try:
                        num = int(name.split(" ")[1])
                        max_num = max(max_num, num)
                    except (IndexError, ValueError):
                        pass

    # Return next available number
    return f"CUSTOM {max_num + 1}"


def update_gpsd_baud_rate(ui_module: UIModule) -> None:
    """
    Updates the GPSD configuration with the current baud rate setting.
    Always updates GPSD config regardless of current GPS type.
    """
    baud_rate = ui_module.config_object.get_option("gps_baud_rate")

    ui_module.message(_("Checking GPS\nconfig..."), 2)
    logger.info(f"Checking GPSD baud rate {baud_rate}")

    try:
        if sys_utils.check_and_sync_gpsd_config(baud_rate):
            ui_module.message(_("GPS config\nupdated"), 2)
        else:
            ui_module.message(_("GPS config\nOK"), 2)
    except Exception as e:
        logger.error(f"Failed to update GPSD config: {e}")
        ui_module.message(_("GPS config\nfailed"), 3)

