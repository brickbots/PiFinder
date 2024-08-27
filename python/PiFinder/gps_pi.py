#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions
"""
import time
from PiFinder.multiproclogging import MultiprocLogging
from gpsdclient import GPSDClient
import logging
import json

logger = logging.getLogger("GPS")

def is_tpv_accurate(tpv_dict):
    """
    Check the accuracy of the GPS fix
    """
    mode = tpv_dict.get("mode", 0)
    error = tpv_dict.get("epx", tpv_dict.get("epy", 499))  # Using horizontal error
    logger.debug(
        "GPS: TPV: mode=%s, error=%s, lat=%s, lon=%s",
        mode,
        error,
        tpv_dict.get("lat"),
        tpv_dict.get("lon"),
    )
    return mode >= 2 and error < 500

def gps_monitor(gps_queue, console_queue, log_queue):
    MultiprocLogging.configurer(log_queue)
    gps_locked = False
    last_sky_update = 0

    with GPSDClient(host="127.0.0.1") as client:
        while True:
            logger.debug("GPS waking")

            try:
                for msg in client.json_stream():
                    current_time = time.time()

                    try:
                        parsed_msg = json.loads(msg)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse JSON: {msg}")
                        continue

                    logger.debug(f"Received message: {parsed_msg.get('class')}")

                    if parsed_msg.get('class') == 'TPV':
                        if is_tpv_accurate(parsed_msg):
                            if parsed_msg.get("lat") and parsed_msg.get("lon"):
                                if not gps_locked:
                                    gps_locked = True
                                    console_queue.put("GPS: Locked")
                                    logger.debug("GPS locked")

                                fix_msg = (
                                    "fix",
                                    {
                                        "lat": parsed_msg.get("lat"),
                                        "lon": parsed_msg.get("lon"),
                                        "altitude": parsed_msg.get("alt", 0),  # Use 'alt' for 2D fix
                                    },
                                )
                                logger.debug("GPS fix: %s", fix_msg)
                                gps_queue.put(fix_msg)

                            if parsed_msg.get("time"):
                                time_msg = ("time", parsed_msg.get("time"))
                                logger.debug("Setting time to %s", parsed_msg.get("time"))
                                gps_queue.put(time_msg)

                    elif parsed_msg.get('class') == 'SKY':
                        if current_time - last_sky_update >= 7:  # Update every 7 seconds
                            satellites = parsed_msg.get("satellites", [])
                            sats_seen = len(satellites)
                            sats_used = sum(1 for sat in satellites if sat.get("used"))
                            num_sats = (sats_seen, sats_used)
                            sat_msg = ("satellites", num_sats)
                            logger.debug("Number of sats seen/used: %i/%i", sats_seen, sats_used)
                            gps_queue.put(sat_msg)
                            last_sky_update = current_time

                    # Break the inner loop after processing a batch of messages
                    if current_time - last_sky_update >= 7:
                        break

            except Exception as e:
                logger.error("Error in GPS monitor: %s", str(e))

            logger.debug("GPS sleeping now for 1s")
            time.sleep(1)  # Sleep for a short time before checking for new messages

        logger.warning("GPS monitor exited unexpectedly")
