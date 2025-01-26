#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions
"""

import asyncio
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.gps_ubx_parser import UBXParser
import logging

logger = logging.getLogger("GPS")
sats = [0,0]

def is_tpv_accurate(tpv_dict, error_info):
    """
    Check the accuracy of the GPS fix
    """
    mode = tpv_dict.get("mode")
    error_2d = error_info['error_2d']
    error_3d = error_info['error_3d']
    logger.debug(
        "GPS: TPV: mode=%s, ecefpAcc=%s, sep=%s, error_2d=%s, error_3d=%s",
        mode,
        tpv_dict.get("ecefpAcc", -1),
        tpv_dict.get("sep", -1),
        error_2d,
        error_3d,
    )
    if mode == 2 and error_2d < 1000:
        return True
    if mode == 3 and error_3d < 500:
        return True
    else:
        return False

async def process_messages(parser, gps_queue, console_queue, error_info):
    gps_locked = False
    async for msg in parser.parse_messages():
        print(msg)
        if msg.get("class") == "SKY":
            logger.debug("GPS: SKY: %s", msg)
            if "hdop" in msg:
                error_info['error_2d'] = msg["hdop"]
            if "pdop" in msg:
                error_info['error_3d'] = msg["pdop"]
            if "nSat" in msg:
                sats_seen = msg["nSat"]
                sats[0] = sats_seen
                gps_queue.put(("satellites", tuple(sats)))
                logger.debug("Number of sats seen: %i", sats_seen)
        elif msg.get("class") == "TPV":
            logger.debug("GPS: TPV: %s", msg)
            if "satellites" in msg:
                sats[1] = msg["satellites"]
                sats_used = msg.get("satellites", 0)
                gps_queue.put(("satellites", tuple(sats)))
                logger.debug("Number of sats used: %i", sats_used)
            if "lat" in msg and "lon" in msg and "altHAE" in msg:
                if not gps_locked:
                    gps_locked = True
                    console_queue.put("GPS: Locked")
                    logger.debug("GPS locked")
                gps_queue.put((
                    "fix",
                    {
                        "lat": msg["lat"],
                        "lon": msg["lon"],
                        "altitude": msg["altHAE"]
                    }
                ))
                logger.debug("GPS fix: %s", msg)
            if "time" in msg:
                gps_queue.put(("time", msg["time"]))
                logger.debug("Setting time to %s", msg["time"])
        await asyncio.sleep(0)

async def gps_main(gps_queue, console_queue, log_queue):
    MultiprocLogging.configurer(log_queue)
    error_info = {'error_2d': 999, 'error_3d': 999}

    while True:
        try:
            parser = await UBXParser.connect(host='127.0.0.1', port=2947)
            await process_messages(parser, gps_queue, console_queue, error_info)
        except Exception as e:
            logger.error(f"Error in GPS monitor: {e}")
            await asyncio.sleep(5)

def gps_monitor(gps_queue, console_queue, log_queue):
    asyncio.run(gps_main(gps_queue, console_queue, log_queue))
