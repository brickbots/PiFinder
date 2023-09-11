#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions

"""
import time
from gpsdclient import GPSDClient
import logging


def is_tpv_accurate(tpv_dict):
    """
    Check the accuracy of the GPS fix
    """
    if tpv_dict.get("mode") == 3 and tpv_dict.get("ecefpAcc") < 100:
        return True
    else:
        logging.debug(f"GPS: TPV accuracy not good enough: {tpv_dict}")
        return False


def gps_monitor(gps_queue, console_queue):
    gps_locked = False
    while True:
        with GPSDClient(host="127.0.0.1") as client:
            # see https://www.mankier.com/5/gpsd_json for the list of fields
            for result in client.dict_stream(convert_datetime=True, filter=["TPV"]):
                if is_tpv_accurate(result):
                    if result.get("lat") and result.get("lon") and result.get("altHAE"):
                        if gps_locked is False:
                            console_queue.put("GPS: Locked")
                            gps_locked = True
                        msg = (
                            "fix",
                            {
                                "lat": result.get("lat"),
                                "lon": result.get("lon"),
                                "altitude": result.get("altHAE"),
                            },
                        )
                        logging.debug(f"GPS fix: {msg}")
                        gps_queue.put(msg)
                    if result.get("time"):
                        msg = ("time", result.get("time"))
                        logging.debug(f"Setting time to {result.get('time')}")
                        gps_queue.put(msg)

        time.sleep(0.5)
