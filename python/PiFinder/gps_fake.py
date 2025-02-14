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

error_countdown = 100 # 200 * 0.5 = 100 seconds
error_start = 10_000 # 100 km
error_stop = 600 # 10s meters
lock_at = 1_000 # 1 km


def gps_monitor(gps_queue, console_queue, log_queue):
    MultiprocLogging.configurer(log_queue)
    time.sleep(5)
    error_in_m = error_start
    delta = (error_start - error_stop) / error_countdown
    lock = False
    i = -1
    while True:
        i += 1
        time.sleep(0.5)
        fix = (
            "fix",
            {"lat": 34.22, "lon": -118.22, "altitude": 22, "source": "fakeGPS", "error_in_m": error_in_m, "lock": lock},
        )
        gps_queue.put(fix)
        if error_in_m < lock_at:
            lock = True
        if error_in_m > error_stop:
            error_in_m -= delta
            
        tm = (
            "time", 
            { "time": datetime.datetime.now() }
        )
        gps_queue.put(tm)

        if (i % 20) == 0:
            i = 0
            logger.debug("GPS fake: %s", fix)
            logger.debug("GPD fake: %s", tm)
