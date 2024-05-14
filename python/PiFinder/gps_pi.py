#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions

"""
import time
from gpsdclient import GPSDClient
import logging
from itertools import islice


def is_tpv_accurate(tpv_dict):
    """
    Check the accuracy of the GPS fix
    """
    error = tpv_dict.get("ecefpAcc", tpv_dict.get("sep", 499))
    # logging.debug("GPS: TPV: mode=%s, error=%s",  tpv_dict.get('mode'), error)
    if tpv_dict.get("mode") == 3 and error < 500:
        return True
    else:
        return False


def gps_monitor(gps_queue, console_queue):
    gps_locked = False
    while True:
        with GPSDClient(host="127.0.0.1") as client:
            # see https://www.mankier.com/5/gpsd_json for the list of fields
            while True:
                logging.debug("GPS waking")
                readings_filter = filter(
                    lambda x: is_tpv_accurate(x),
                    client.dict_stream(convert_datetime=True, filter=["TPV", "SKY"]),
                )
                readings_list = list(islice(readings_filter, 10))
                if readings_list:
                    result = min(
                        readings_list,
                        key=lambda x: x.get("ecefpAcc", x.get("sep", float("inf"))),
                    )
                    logging.debug("last reading is %s", result)
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
                        logging.debug("GPS fix: %s", msg)
                        gps_queue.put(msg)

                    # Look for any time-bearing packet and SKY packet to get satellite information
                    time_found = False
                    num_satellites = None

                    # search from the newest first, quit if something is found
                    for result in reversed(readings_list):
                        if not time_found and result.get("time"):
                            msg = ("time", result.get("time"))
                            logging.debug("Setting time to %s", result.get("time"))
                            gps_queue.put(msg)
                            time_found = True  # Stop looking for time once found

                        if (
                            not num_satellites
                            and result["class"] == "SKY"
                            and "satellites" in result
                        ):
                            logging.debug("SKY packet found: {result['satellites']}")
                            num_satellites = len(result["satellites"])
                        msg = ("satellites", num_satellites)
                        logging.debug("Number of satellites seen: %d", num_satellites)
                        gps_queue.put(msg)

                else:
                    logging.debug("GPS client queue is empty")
                logging.debug("GPS sleeping now")
                time.sleep(7)
