#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions
"""

from PiFinder.multiproclogging import MultiprocLogging
from gpsdclient import GPSDClient
import logging

logger = logging.getLogger("GPS")

error_2d = 999
error_3d = 999
error_in_m = 999


def is_tpv_accurate(tpv_dict):
    """
    Check the accuracy of the GPS fix
    """
    global error_2d, error_3d, error_in_m
    # get the ecefpAcc if present, else get sep, else use 499
    # error = tpv_dict.get("ecefpAcc", tpv_dict.get("sep", 499))
    mode = tpv_dict.get("mode")
    logger.debug(
        "GPS: TPV: mode=%s, ecefpAcc=%s, sep=%s, error_2d=%s, error_3d=%s",
        mode,
        # error,
        tpv_dict.get("ecefpAcc", -1),
        tpv_dict.get("sep", -1),
        error_2d,
        error_3d,
    )
    if mode == 2 and error_2d < 1000:
        error_in_m = error_2d
        return True
    if mode == 3 and error_3d < 500:
        error_in_m = error_3d
        return True
    else:
        return False


def gps_main(gps_queue, console_queue, log_queue):
    global error_2d, error_3d, error_in_m
    MultiprocLogging.configurer(log_queue)
    logger.info("Using GPSD GPS code")
    gps_locked = False

    while True:
        try:
            with GPSDClient(host="127.0.0.1") as client:
                for result in client.dict_stream(
                    convert_datetime=True, filter=["TPV", "SKY"]
                ):
                    if result["class"] == "TPV" and is_tpv_accurate(result):
                        logger.debug("last reading is %s", result)
                        if (
                            result.get("lat")
                            and result.get("lon")
                            and result.get("altHAE")
                        ):
                            if not gps_locked:
                                gps_locked = True
                                console_queue.put("GPS: Locked")
                                logger.debug("GPS locked")
                            msg = (
                                "fix",
                                {
                                    "lat": result.get("lat"),
                                    "lon": result.get("lon"),
                                    "altitude": result.get("altHAE"),
                                    "source": "GPS",
                                    "lock": True,
                                    "lock_type": result.get("mode", 0),
                                    "error_in_m": error_in_m,
                                },
                            )
                            logger.debug("GPS fix: %s", msg)
                            gps_queue.put(msg)

                        if result.get("time"):
                            msg = ("time", result.get("time"))
                            logger.debug("Setting time to %s", result.get("time"))
                            gps_queue.put(msg)

                    if result["class"] == "SKY":
                        logger.debug("GPS: SKY: %s", result)
                        print("GPS: SKY: %s", result)
                        if result["class"] == "SKY":
                            error_2d = result.get("hdop", 999)
                            error_3d = result.get("pdop", 999)
                        if result["class"] == "SKY" and "nSat" in result:
                            sats_seen = result["nSat"]
                            sats_used = result["uSat"]
                            num_sats = (sats_seen, sats_used)
                            msg = ("satellites", num_sats)
                            logger.debug("Number of sats seen: %i", sats_seen)
                            gps_queue.put(msg)
        except Exception as e:
            logger.error(f"Error in GPS monitor: {e}")


# To run the GPS monitor
def gps_monitor(gps_queue, console_queue, log_queue):
    gps_main(gps_queue, console_queue, log_queue)
