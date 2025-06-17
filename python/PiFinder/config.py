#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module handles non-volatile config options
"""

import json
import os
from pathlib import Path
from PiFinder import utils, equipment, locations
from typing import Any


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
        cwd = Path.cwd()
        self.config_file_path = Path(utils.data_dir, "config.json")

        self.default_file_path = Path(cwd, "../default_config.json")
        if not os.path.exists(self.config_file_path):
            self._config_dict = {}
        else:
            with open(self.config_file_path, "r") as config_file:
                print("Loading config from", self.config_file_path)
                self._config_dict = json.load(config_file)

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

            self.equipment = equipment.Equipment.from_dict(eq_config)

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
