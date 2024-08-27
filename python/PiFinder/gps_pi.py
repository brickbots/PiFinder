#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions

"""

import time
from PiFinder.multiproclogging import MultiprocLogging
from gpsdclient import GPSDClient
import logging
from itertools import islice

logger = logging.getLogger("GPS")


def is_tpv_accurate(tpv_dict):
    """
    Check the accuracy of the GPS fix
    """
    error = tpv_dict.get("ecefpAcc", tpv_dict.get("sep", 499))
    logger.debug(
        "GPS: TPV: mode=%s, error=%s, ecefpAcc=%s, sep=%s",
        tpv_dict.get("mode"),
        error,
        tpv_dict.get("ecefpAcc", -1),
        tpv_dict.get("sep", -1),
    )
    if tpv_dict.get("mode") >= 2 and error < 500:
        return True
    else:
        return False


def gps_monitor(gps_queue, console_queue, log_queue):
    MultiprocLogging.configurer(log_queue)
    gps_locked = False
    last_sky_update = 0

    with GPSDClient(host="127.0.0.1") as client:
        while True:
            logger.debug("GPS waking")

            for msg in client.dict_stream(convert_datetime=True):
                current_time = time.time()

                if msg['class'] == 'TPV':
                    if is_tpv_accurate(msg):
                        if msg.get("lat") and msg.get("lon") and msg.get("altHAE"):
                            if not gps_locked:
                                gps_locked = True
                                console_queue.put("GPS: Locked")
                                logger.debug("GPS locked")

                            fix_msg = (
                                "fix",
                                {
                                    "lat": msg.get("lat"),
                                    "lon": msg.get("lon"),
                                    "altitude": msg.get("altHAE"),
                                },
                            )
                            logger.debug("GPS fix: %s", fix_msg)
                            gps_queue.put(fix_msg)

                        if msg.get("time"):
                            time_msg = ("time", msg.get("time"))
                            logger.debug("Setting time to %s", msg.get("time"))
                            gps_queue.put(time_msg)

                elif msg['class'] == 'SKY':
                    if current_time - last_sky_update >= 7:  # Update every 7 seconds
                        if "nSat" in msg:
                            sats_seen = msg["nSat"]
                            sats_used = msg["uSat"]
                            num_sats = (sats_seen, sats_used)
                            sat_msg = ("satellites", num_sats)
                            logger.debug("Number of sats seen/used: %i/%i", sats_seen, sats_used)
                            gps_queue.put(sat_msg)
                        last_sky_update = current_time

                # Break the inner loop after processing a batch of messages
                if current_time - last_sky_update >= 7:
                    break

            logger.debug("GPS sleeping now for 1s")
            time.sleep(1)
