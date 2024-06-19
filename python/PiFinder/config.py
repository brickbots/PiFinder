#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module handles non-volatile config options
"""

import json
import os
from pathlib import Path
from PiFinder import utils


class Config:
    def __init__(self):
        """
        load all settings from config file
        """
        cwd = Path.cwd()
        self.config_file_path = Path(utils.data_dir, "config.json")

        self.default_file_path = Path(cwd, "../default_config.json")
        if not os.path.exists(self.config_file_path):
            self._config_dict = {}
        else:
            with open(self.config_file_path, "r") as config_file:
                self._config_dict = json.load(config_file)

        # open default default_config
        with open(self.default_file_path, "r") as config_file:
            self._default_config_dict = json.load(config_file)

    def dump_config(self):
        """
        Write config to config file
        """
        with open(self.config_file_path, "w") as config_file:
            json.dump(self._config_dict, config_file, indent=4)

    def set_option(self, option, value):
        self._config_dict[option] = value
        self.dump_config()

    def get_option(self, option):
        return self._config_dict.get(
            option, self._default_config_dict.get(option, None)
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
