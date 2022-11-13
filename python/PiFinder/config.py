#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module handles non-volitile config options
"""
import json


class Config:
    def __init__(self):
        """
        load all settings from config file
        """
        with open("/home/pifinder/PiFinder/config.json", "r") as config_file:
            self._config_dict = json.load(config_file)

    def set_option(self, option, value):
        self._config_dict[option] = value
        with open("/home/pifinder/PiFinder/config.json", "w") as config_file:
            json.dump(self._config_dict, config_file, indent=4)

    def get_option(self, option):
        return self._config_dict[option]
