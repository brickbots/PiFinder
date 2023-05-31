#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions

"""
import time
from PiFinder import gps


def gps_monitor(gps_queue, console_queue):
    session = gps.gps(mode=gps.WATCH_ENABLE)
    gps_locked = False
    while True:
        if session.read() == 0:
            if session.valid:
                if session.fix.mode == 3:  # 3d fix
                    if (
                        gps.isfinite(session.fix.latitude)
                        and gps.isfinite(session.fix.longitude)
                        and gps.isfinite(session.fix.altitude)
                    ):
                        if gps_locked == False:
                            console_queue.put("GPS: Locked")
                            gps_locked = True
                        msg = (
                            "fix",
                            {
                                "lat": session.fix.latitude,
                                "lon": session.fix.longitude,
                                "altitude": session.fix.altitude,
                            },
                        )
                        gps_queue.put(msg)

                if gps.TIME_SET and session.utc:
                    msg = ("time", session.utc)
                    gps_queue.put(msg)

        else:
            print("Error in GPS session")

        time.sleep(0.5)
