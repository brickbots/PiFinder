#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions

"""

import time
import datetime


def gps_monitor(gps_queue, console_queue):
    time.sleep(5)
    while True:
        time.sleep(0.5)
        msg = (
            "fix",
            {"lat": 34.22, "lon": -118.22, "altitude": 22},
        )
        gps_queue.put(msg)

        msg = ("time", datetime.datetime.now())
        gps_queue.put(msg)
