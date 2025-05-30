#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""

import logging
from PiFinder import state_utils
from PiFinder.ui.base import UIModule
from PiFinder.locations import Location
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.ui.textentry import UITextEntry

logger = logging.getLogger("GPS.status")


class UIGPSStatus(UIModule):
    """
    UI for seeing GPS status
    """

    __title__ = "GPS"
    _lock_type_dict = {
        0: "Limited",  # there's no lock but we accept the position due to low enough error value
        1: "Basic",  # coarse fix, does this happen?
        2: "Accurate",  # 2D Fix
        3: "Precise",  # 3D Fix
    }
    _display_mode_list = ["large", "detailed"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        # Marking menu definition
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(
                label="Save", callback=self.mm_save_location, enabled=True
            ),
            right=MarkingMenuOption(
                label="Lock", callback=self.mm_lock_location, enabled=True
            ),
            up=MarkingMenuOption(),  # Empty option
            down=MarkingMenuOption(),  # Empty option
        )

    def _send_fix_message(self, gps_reading, source):
        """Helper to send fix message to GPS queue"""
        self.command_queues["gps"].put(
            (
                "fix",
                {
                    "lat": gps_reading.lat,
                    "lon": gps_reading.lon,
                    "altitude": gps_reading.altitude,
                    "source": source,
                    "lock": True,
                    "lock_type": gps_reading.lock_type,
                    "error_in_m": gps_reading.error_in_m,
                },
            )
        )

    def mm_save_location(self, marking_menu, menu_item):
        """Save current location to the locations config"""
        gps_reading = self.shared_state.location()

        # Create text entry definition for location name
        item_definition = {
            "name": "Location Name",
            "class": UITextEntry,
            "callback": lambda name: self._save_location_with_name(name, gps_reading),
            "initial_text": f"Loc {len(self.config_object.locations.locations) + 1}",
            "mode": "text_entry",  # This will be passed through item_definition
        }

        # Add text entry to UI stack
        self.add_to_stack(item_definition)
        return True

    def _save_location_with_name(self, name: str, gps_reading):
        """Callback for text entry - saves location with provided name and sets as current location"""
        # Create new Location object from GPS reading
        new_location = Location(
            name=name,
            latitude=gps_reading.lat,
            longitude=gps_reading.lon,
            height=gps_reading.altitude,
            error_in_m=gps_reading.error_in_m,
            source=gps_reading.source,
        )

        # Add to locations config
        self.config_object.locations.add_location(new_location)
        self.config_object.save_locations()

        # Set as current location
        self._send_fix_message(gps_reading, f"Saved: {name}")

        # Show confirmation message
        self.message("Location saved", timeout=2)

    def mm_lock_location(self, marking_menu, menu_item):
        """Lock to current location"""
        gps_reading = self.shared_state.location()

        # Set current location
        self._send_fix_message(gps_reading, "GPS")

        # Show confirmation message
        self.message("Location locked", timeout=2)
        return True

    def _get_error_string(self, error: float) -> str:
        if error > 1000:
            return f"{error/1000:.1f} km"
        else:
            return f"{error:.0f} m"

    def active(self):
        self.command_queues["camera"].put("stop")

    def inactive(self):
        self.command_queues["camera"].put("start")

    def update(self, force=False):
        state_utils.sleep_for_framerate(self.shared_state)
        self.clear_screen()
        draw_pos = self.display_class.titlebar_height + 1
        location = self.shared_state.location()
        sats = self.shared_state.sats()
        if sats is None:
            sats = (0, 0)

        # Status message
        if location.lock_type and location.lock_type > 1:
            self.draw.text(
                (20, draw_pos),
                "GPS Locked",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
        else:
            self.draw.text(
                (5, draw_pos),
                "Lock boost on",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
        draw_pos += 16
        if self.display_mode == "large":
            if location.lock_type and location.lock_type > 1:
                self.draw.text(
                    (25, draw_pos),
                    "You are ready",
                    font=self.fonts.base.font,
                    fill=self.colors.get(192),
                )
                draw_pos += 10
                self.draw.text(
                    (35, draw_pos),
                    "to observe!",
                    font=self.fonts.base.font,
                    fill=self.colors.get(192),
                )
                draw_pos += 15
            else:
                self.draw.text(
                    (5, draw_pos),
                    "Stay on this screen",
                    font=self.fonts.base.font,
                    fill=self.colors.get(192),
                )
                draw_pos += 10
                self.draw.text(
                    (10, draw_pos),
                    "for quicker lock",
                    font=self.fonts.base.font,
                    fill=self.colors.get(192),
                )
                draw_pos += 15

            # Lock status
            self.draw.text(
                (10, draw_pos),
                "Lock Type:",
                font=self.fonts.bold.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10
            self.draw.text(
                (10, draw_pos),
                f"{'None' if not location.lock else self._lock_type_dict[location.lock_type]}",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            draw_pos += 18

            # Satellite info
            self.draw.text(
                (10, draw_pos),
                "Sats seen/used:",
                font=self.fonts.bold.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10

            # Satellite info
            self.draw.text(
                (10, draw_pos),
                f"{sats[0]}/{sats[1]}",
                font=self.fonts.large.font,
                fill=self.colors.get(192),
            )

            self.draw.text(
                (15, self.display_class.resY - self.fonts.base.height - 2),
                f"{self._SQUARE_} Toggle Details",
                font=self.fonts.base.font,
                fill=self.colors.get(255),
            )

        if self.display_mode == "detailed":
            # Satellite info
            self.draw.text(
                (0, draw_pos),
                f"Sats seen/used: {sats[0]}/{sats[1]}",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10

            # Error display
            self.draw.text(
                (0, draw_pos),
                f"Error: {self._get_error_string(location.error_in_m)}",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10

            # Lock status
            self.draw.text(
                (0, draw_pos),
                f"Lock:  {'No' if not location.lock else self._lock_type_dict[location.lock_type]}",
                font=self.fonts.base.font,
                fill=self.colors.get(255),
            )
            draw_pos += 10

            # Position data if locked
            self.draw.text(
                (0, draw_pos),
                f"Lat:   {location.lat:.5f}",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10

            self.draw.text(
                (0, draw_pos),
                f"Lon:   {location.lon:.5f}",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10

            self.draw.text(
                (0, draw_pos),
                f"Alt:   {location.altitude:.1f} m",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10

            time = self.shared_state.local_datetime()
            self.draw.text(
                (0, draw_pos),
                f"Time:  {time.strftime('%H:%M:%S') if time else '---'}",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10
            self.draw.text(
                (0, draw_pos),
                f"From:  {location.source}",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10
        return self.screen_update()
