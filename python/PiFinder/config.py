#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module handles non-volatile config options
"""

import json
import math
import os
from pathlib import Path
from PiFinder import utils, equipment, locations
from typing import Any, Optional
import logging

logger = logging.getLogger("config")

_LEGACY_SCREEN_DIRECTIONS = {
    "v4_left": "rev4_left",
    "v4_right": "rev4_right",
    "v4_straight": "rev4_straight",
}


# (Y, X) centre of the 512x512 camera image: "no alignment offset known".
IMAGE_CENTER_PIXEL = (256.0, 256.0)


def _as_target_pixel(value) -> Optional[tuple[float, float]]:
    """``value`` as a finite (Y, X) float pair, or None if it is not one."""
    if not isinstance(value, (list, tuple)):
        return None
    try:
        y, x = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(y) and math.isfinite(x)):
        return None
    return (y, x)


class Config:
    def __init__(self):
        """
        load all settings from config file
        """
        # Set up session config items
        # These are transient
        self._session_config_dict = {}
        self.load_config()

    def load_config(self):
        """
        Loads all config from disk useful if another
        process has changed config
        """
        self.config_file_path = Path(utils.data_dir, "config.json")

        self.default_file_path = Path(utils.pifinder_dir, "default_config.json")
        if not os.path.exists(self.config_file_path):
            self._config_dict = {}
        else:
            with open(self.config_file_path, "r") as config_file:
                logger.info("Loading config from %s", self.config_file_path)
                self._config_dict = json.load(config_file)

        # Configs written before the rev4 build variants were renamed
        # (v4_* -> rev4_*) still hold the old values; unknown values crash
        # ImuDeadReckoning, so normalize on every load.
        legacy_direction = self._config_dict.get("screen_direction")
        if legacy_direction in _LEGACY_SCREEN_DIRECTIONS:
            self._config_dict["screen_direction"] = _LEGACY_SCREEN_DIRECTIONS[
                legacy_direction
            ]

        # open default default_config
        with open(self.default_file_path, "r") as config_file:
            self._default_config_dict = json.load(config_file)

        # Load the equipment config
        eq_config = self.get_option("equipment")
        if eq_config is None:
            self.equipment = equipment.Equipment(telescopes=[], eyepieces=[])
        else:
            # do a little bit of validation here

            # get default equipment
            default_eq = self._default_config_dict.get("equipment")
            if not default_eq:
                # if we don't have defaults, something is very wrong
                self.equipment = equipment.Equipment(telescopes=[], eyepieces=[])
                return

            if not eq_config.get("telescopes", []):
                # use default valuES
                eq_config["telescopes"] = default_eq["telescopes"]

            if not eq_config.get("eyepieces", []):
                # use default valuES
                eq_config["eyepieces"] = default_eq["eyepieces"]

            if eq_config.get("active_telescope_index", 1000) >= len(
                eq_config["telescopes"]
            ):
                eq_config["active_telescope_index"] = 0

            if eq_config.get("active_eyepiece_index", 1000) >= len(
                eq_config["eyepieces"]
            ):
                eq_config["active_eyepiece_index"] = 0

            # A telescope's alignment point is only ever written by the
            # alignment screens, but a hand edit can still break one.  Drop
            # an unusable point here (that telescope falls back to the global
            # target_pixel) rather than let from_dict raise and throw away
            # every telescope and eyepiece.
            for telescope in eq_config["telescopes"]:
                if not isinstance(telescope, dict):
                    continue
                stored = telescope.get("target_pixel")
                if stored is not None and _as_target_pixel(stored) is None:
                    logger.warning(
                        "Ignoring unusable alignment point %r on telescope %r",
                        stored,
                        telescope.get("name"),
                    )
                    telescope["target_pixel"] = None

            try:
                self.equipment = equipment.Equipment.from_dict(eq_config)
            except (ValueError, TypeError, KeyError):
                # A value the equipment dataclasses can't decode used to
                # abort main() before the UI came up — an unusable PiFinder
                # (#291).  Fall back to the defaults and keep booting; the
                # web forms validate everything they write, so a config
                # that lands here was hand-edited or written by an older
                # release.
                logger.exception(
                    "Could not load saved equipment; falling back to defaults"
                )
                self.equipment = equipment.Equipment.from_dict(default_eq)

        # Load the locations config
        loc_config = self.get_option("locations")
        if loc_config is None:
            self.locations = locations.Locations(locations=[])
        else:
            self.locations = locations.Locations.from_dict(loc_config)

    def save_equipment(self):
        """
        Saves the equipment object state
        """
        self.set_option("equipment", self.equipment.to_dict())

    def save_locations(self):
        """
        Saves the locations object state
        """
        self.set_option("locations", self.locations.to_dict())

    def dump_config(self):
        """
        Write config to config file
        """
        with open(self.config_file_path, "w") as config_file:
            json.dump(self._config_dict, config_file, indent=4)

    def set_option(self, option, value):
        if option.startswith("session."):
            self._session_config_dict[option] = value
        elif option.startswith("equipment."):
            option = option.split(".")[1]
            if option == "active_telescope":
                self.equipment.set_active_telescope(value)
            if option == "active_eyepiece":
                self.equipment.set_active_eyepiece(value)

            self.save_equipment()

        elif option.startswith("locations."):
            # Just save locations when any locations option changes
            self.save_locations()

        else:
            self._config_dict[option] = value
            self.dump_config()

    def get_option(self, option, default: Any = None):
        if option.startswith("session."):
            return self._session_config_dict.get(option, default)
        elif option.startswith("equipment."):
            option = option.split(".")[1]
            if option == "active_telescope":
                return self.equipment.active_telescope
            if option == "active_eyepiece":
                return self.equipment.active_eyepiece
        elif option.startswith("locations."):
            option = option.split(".")[1]
            if option == "default":
                return self.locations.default_location
        else:
            return self._config_dict.get(
                option, self._default_config_dict.get(option, default)
            )

    def active_target_pixel(self) -> tuple[float, float]:
        """The alignment point the solver should use now, as (Y, X).

        The active telescope's own point if it has been aligned; otherwise
        the global ``target_pixel`` (the point every telescope shared before
        alignment became per-telescope, and the one used when no telescope
        is selected); otherwise the image centre.  A stored value that is
        not a usable pixel is skipped rather than raised, so a hand-edited
        config cannot stop the solver.
        """
        telescope = self.equipment.active_telescope
        if telescope is not None:
            pixel = _as_target_pixel(telescope.target_pixel)
            if pixel is not None:
                return pixel
        pixel = _as_target_pixel(self.get_option("target_pixel"))
        if pixel is not None:
            return pixel
        return IMAGE_CENTER_PIXEL

    def save_target_pixel(self, target_pixel) -> None:
        """Persist a new alignment point, (Y, X), for the active telescope.

        With no telescope selected it goes to the global ``target_pixel``,
        which is also what every not-yet-aligned telescope falls back to.
        """
        pixel = _as_target_pixel(target_pixel)
        if pixel is None:
            raise ValueError(f"Not a target pixel: {target_pixel!r}")
        telescope = self.equipment.active_telescope
        if telescope is None:
            self.set_option("target_pixel", list(pixel))
        else:
            telescope.target_pixel = list(pixel)
            self.save_equipment()

    def reset_filters(self):
        """
        Removes all filter. keys from the
        config dict and writes it out.
        Effectively resetting filters to default
        """
        keys_to_remove = []
        for _k in self._config_dict:
            if _k.startswith("filter."):
                keys_to_remove.append(_k)

        for _k in keys_to_remove:
            self._config_dict.pop(_k)

        self.dump_config()

    def __str__(self):
        return str(self._config_dict)

    def __repr__(self):
        return str(self._config_dict)
