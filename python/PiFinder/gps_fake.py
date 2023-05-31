#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions

"""
import time


def gps_monitor(gps_queue, console_queue):
    gps_locked = False
    while True:
        """
        Just sleep for now
        """
        time.sleep(0.5)
