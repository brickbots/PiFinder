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

def gps_monitor(gps_queue, console_queue, log_queue):
    MultiprocLogging.configurer(log_queue)
    time.sleep(5)
    i = -1
    while True:
        i += 1       
        time.sleep(0.5)
        fix = (
            "fix",
            {"lat": 34.22, "lon": -118.22, "altitude": 22},
        )
        gps_queue.put(fix)
        tm = ("time", datetime.datetime.now())
        gps_queue.put(tm)

        if (i % 20) == 0:
            i = 0
            logger.debug("GPS fake: %s", fix)
            logger.debug("GPD fake: %s", tm)

