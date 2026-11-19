#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module handles non-volatile config options
"""

import fcntl
import json
import os
import tempfile
from pathlib import Path
from PiFinder import utils, equipment, locations
from typing import Any, Callable, Optional
import logging

logger = logging.getLogger("config")

_LEGACY_SCREEN_DIRECTIONS = {
    "v4_left": "rev4_left",
    "v4_right": "rev4_right",
    "v4_straight": "rev4_straight",
}


# The target pixel lives in the square native camera frame the solver works
# in (see SharedStateObj.target_pixel); (Y, X) centre means "no alignment
# offset known".
CAMERA_NATIVE_RES = 512
IMAGE_CENTER_PIXEL = (CAMERA_NATIVE_RES / 2, CAMERA_NATIVE_RES / 2)


def _as_target_pixel(value) -> Optional[tuple[float, float]]:
    """``value`` as a (Y, X) float pair inside the camera frame, or None.

    Anything else -- the wrong shape, a non-number, a bool (which float()
    would happily turn into 0 or 1), NaN/inf, or a pixel off the frame -- is
    not a point the solver can use.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(isinstance(v, bool) for v in value):
        return None
    try:
        y, x = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not all(0.0 <= v <= CAMERA_NATIVE_RES for v in (y, x)):
        return None  # also rejects NaN, which fails every comparison
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

    def _persist(
        self,
        changes: Optional[dict] = None,
        remove: Optional[Callable[[str], bool]] = None,
    ) -> None:
        """Write ``changes`` into config.json, leaving every other key as is.

        Each process (UI, camera, web server, integrator...) holds its own
        Config, read when it started.  Writing that whole dict back would
        revert everything other processes have saved since -- the camera
        process saving an exposure used to wipe an alignment made in the UI
        moments before.  So a save re-reads the file and changes only its
        own keys.  ``remove`` drops every on-disk key it returns True for.

        The read-modify-write runs under an exclusive lock, so two processes
        saving at once cannot drop each other's key, and the file is
        replaced atomically, so a reader never sees half of it.
        """
        changes = changes or {}
        lock_path = self.config_file_path.with_name(
            "." + self.config_file_path.name + ".lock"
        )
        with open(lock_path, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            on_disk = self._read_config_file()
            if on_disk is None:
                # Missing or unreadable: what this process knows is the best
                # available copy of everything else.
                on_disk = dict(self._config_dict)
            if remove is not None:
                for key in [k for k in on_disk if remove(k)]:
                    del on_disk[key]
            on_disk.update(changes)
            self._write_config_file(on_disk)

    def _read_config_file(self) -> Optional[dict]:
        """The settings currently on disk, or None if there are none."""
        try:
            with open(self.config_file_path, "r") as config_file:
                on_disk = json.load(config_file)
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            logger.exception("Could not read %s before saving", self.config_file_path)
            return None
        return on_disk if isinstance(on_disk, dict) else None

    def _write_config_file(self, settings: dict) -> None:
        """Replace config.json with ``settings`` in one atomic step."""
        directory = self.config_file_path.parent
        try:
            mode = os.stat(self.config_file_path).st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644
        fd, tmp_path = tempfile.mkstemp(
            dir=directory, prefix=".config.", suffix=".json.tmp"
        )
        try:
            with os.fdopen(fd, "w") as tmp_file:
                json.dump(settings, tmp_file, indent=4)
            os.chmod(tmp_path, mode)  # mkstemp creates the file 0600
            os.replace(tmp_path, self.config_file_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

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
            self._persist({option: value})

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

        def is_filter(key: str) -> bool:
            return key.startswith("filter.")

        for _k in [k for k in self._config_dict if is_filter(k)]:
            self._config_dict.pop(_k)

        self._persist(remove=is_filter)

    def __str__(self):
        return str(self._config_dict)

    def __repr__(self):
        return str(self._config_dict)
