#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions

"""

import time
import datetime
import logging

from PiFinder.multiproclogging import MultiprocLogging

logger = logging.getLogger("GPS")

# Have a linear count-down in error, simulating a bad fix, that gets better

error_delta = 100 # 200 * 0.5 = 100 seconds
error_start = 2_000 # 100 km
lock_at = 1_000 # 1 km
fix_2d = 500 # m
fix_3d = 200 # m
error_stop = 200 # 10s meters


def gps_monitor(gps_queue, console_queue, log_queue):
    MultiprocLogging.configurer(log_queue)
    time.sleep(5)
    error_in_m = error_start
    lock = False
    lock_type = None
    i = -1
    while True:
        i += 1
        time.sleep(0.5)
        fix = (
            "fix",
            {"lat": 34.22, "lon": -118.22, "altitude": 22, "source": "fakeGPS", "error_in_m": error_in_m, "lock": lock, "lock_type": lock_type},
        )
        gps_queue.put(fix)
        if error_in_m < lock_at:
            lock = True
            lock_type = 0
        if error_in_m < fix_2d:
            lock_type = 2
        if error_in_m < fix_3d:
            lock_type = 3
        if error_in_m >= error_stop:
            error_in_m -= error_delta
            
        tm = (
            "time", 
            { "time": datetime.datetime.now() }
        )
        gps_queue.put(tm)

        if (i % 20) == 0:
            i = 0
            logger.debug("GPS fake: %s", fix)
            logger.debug("GPD fake: %s", tm)
