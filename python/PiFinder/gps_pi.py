#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions

"""

import time
from gpsdclient import GPSDClient
import logging
from itertools import islice

logger = logging.getLogger("GPS")


def is_tpv_accurate(tpv_dict):
    """
    Check the accuracy of the GPS fix
    """
    error = tpv_dict.get("ecefpAcc", tpv_dict.get("sep", 499))
    # logger.debug("GPS: TPV: mode=%s, error=%s",  tpv_dict.get('mode'), error)
    if tpv_dict.get("mode") >= 2 and error < 500:
        return True
    else:
        return False


def gps_monitor(gps_queue, console_queue):
    gps_locked = False
    while True:
        with GPSDClient(host="127.0.0.1") as client:
            # see https://www.mankier.com/5/gpsd_json for the list of fields
            while True:
                logger.debug("GPS waking")
                readings_filter = filter(
                    lambda x: is_tpv_accurate(x),
                    client.dict_stream(convert_datetime=True, filter=["TPV"]),
                )
                sky_filter = client.dict_stream(convert_datetime=True, filter=["SKY"])
                readings_list = list(islice(readings_filter, 10))
                sky_list = list(islice(sky_filter, 10))
                if readings_list:
                    result = min(
                        readings_list,
                        key=lambda x: x.get("ecefpAcc", x.get("sep", float("inf"))),
                    )
                    logger.debug("last reading is %s", result)
                    if result.get("lat") and result.get("lon") and result.get("altHAE"):
                        if gps_locked is False:
                            gps_locked = True
                            console_queue.put("GPS: Locked")
                        msg = (
                            "fix",
                            {
                                "lat": result.get("lat"),
                                "lon": result.get("lon"),
                                "altitude": result.get("altHAE"),
                            },
                        )
                        logger.debug("GPS fix: %s", msg)
                        gps_queue.put(msg)

                    # search from the newest first, quit if something is found
                    for result in reversed(readings_list):
                        if result.get("time"):
                            msg = ("time", result.get("time"))
                            logger.debug("Setting time to %s", result.get("time"))
                            gps_queue.put(msg)
                            break
                else:
                    logger.debug("GPS TPV client queue is empty")

                if sky_list:
                    # search from the newest first, quit if something is found
                    for result in reversed(sky_list):
                        if result["class"] == "SKY" and "nSat" in result:
                            sats_seen = result["nSat"]
                            sats_used = result["uSat"]
                            num_sats = (sats_seen, sats_used)
                            msg = ("satellites", num_sats)
                            logger.debug("Number of sats seen: %i", num_sats)
                            gps_queue.put(msg)
                            break
                logger.debug("GPS sleeping now")
                time.sleep(7)
