#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module handles non-volitile config options
"""
import json, os


class Config:
    def __init__(self):
        """
        load all settings from config file
        """
        config_file_path = "/home/pifinder/PiFinder/config.json"
        default_file_path = "/home/pifinder/PiFinder/default_config.json"
        if not os.path.exists(config_file_path):
            config_file_path = default_file_path

        with open(config_file_path, "r") as config_file:
            self._config_dict = json.load(config_file)

    def set_option(self, option, value):
        self._config_dict[option] = value
        with open("/home/pifinder/PiFinder/config.json", "w") as config_file:
            json.dump(self._config_dict, config_file, indent=4)

    def get_option(self, option):
        return self._config_dict[option]
