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


def gpsd_time_message(tpv_dict, gps_locked=False):
    """Build a GPS time message even before the position fix is accurate."""
    gps_time = tpv_dict.get("time")
    if not gps_time:
        return None

    content = {
        "time": gps_time,
        "source": "GPSD",
        "mode": tpv_dict.get("mode", 0),
        "lock": gps_locked,
    }
    if gps_locked:
        content["error_in_m"] = error_in_m
    return "time", content


def gpsd_sky_time_sample(sky_dict):
    """Build a monitor-only GPS time candidate from SKY reports."""
    gps_time = sky_dict.get("time")
    if not gps_time:
        return None

    return (
        "time_sample",
        {
            "time": gps_time,
            "source": "GPSD-SKY",
            "valid": False,
            "satellites_seen": sky_dict.get("nSat"),
            "satellites_used": sky_dict.get("uSat"),
            "hdop": sky_dict.get("hdop"),
            "pdop": sky_dict.get("pdop"),
        },
    )


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
                    if result["class"] == "TPV":
                        gps_accurate = is_tpv_accurate(result)

                        time_msg = gpsd_time_message(result, gps_accurate)
                        if time_msg is not None:
                            logger.debug("Setting GPSD time to %s", result.get("time"))
                            gps_queue.put(time_msg)

                    if result["class"] == "TPV" and gps_accurate:
                        logger.debug("last accurate reading is %s", result)
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

                    if result["class"] == "SKY":
                        logger.debug("GPS: SKY: %s", result)
                        print("GPS: SKY: %s", result)
                        time_sample = gpsd_sky_time_sample(result)
                        if time_sample is not None:
                            gps_queue.put(time_sample)
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
