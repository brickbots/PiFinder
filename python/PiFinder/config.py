#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module handles non-volitile config options
"""
import json, os
from pathlib import Path


class Config:
    def __init__(self):
        """
        load all settings from config file
        """
        cwd = Path.cwd()
        config_file_path = Path(cwd, "../config.json")
        default_file_path = Path(cwd, "../default_config.json")
        if not os.path.exists(config_file_path):
            self._config_dict = {}
        else:
            with open(config_file_path, "r") as config_file:
                self._config_dict = json.load(config_file)

        # open default default_config
        with open(default_file_path, "r") as config_file:
            self._default_config_dict = json.load(config_file)

    def set_option(self, option, value):
        self._config_dict[option] = value
        with open(config_file_path, "w") as config_file:
            json.dump(self._config_dict, config_file, indent=4)

    def get_option(self, option):
        return self._config_dict.get(option, self._default_config_dict[option])
