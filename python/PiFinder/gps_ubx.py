#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions
"""

import asyncio
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.gps_ubx_parser import UBXParser
import logging

logger = logging.getLogger("GPS.parser")
sats = [0, 0]

MAX_GPS_ERROR = 50000  # 50 km


async def process_messages(parser, gps_queue, console_queue, error_info):
    gps_locked = False
    got_sat_update = False  # Track if we got a NAV-SAT message this cycle

    async for msg in parser.parse_messages():
        msg_class = msg.get("class", "")
        logger.debug("GPS: %s: %s", msg_class, msg)

        if msg_class == "NAV-DOP":
            error_info["error_2d"] = msg["hdop"]
            error_info["error_3d"] = msg["pdop"]

        elif msg_class == "NAV-SVINFO" and not got_sat_update:
            # Fallback satellite info if NAV-SAT not available
            if "nSat" in msg:
                # uSat is also in the message but contains stale info
                sats_seen = msg["nSat"]
                sats[0] = sats_seen
                gps_queue.put(("satellites", tuple(sats)))
                logger.debug("Number of sats (SVINFO) seen: %i", sats_seen)

        elif msg_class == "NAV-SAT":
            # Preferred satellite info source - not seen in the current pifinder gps versions
            sats_seen = msg["nSat"]
            sats_used = sum(
                1 for sat in msg.get("satellites", []) if sat.get("used", False)
            )
            sats[0] = sats_seen
            sats[1] = sats_used
            gps_queue.put(("satellites", tuple(sats)))
            logger.debug(
                "Number of sats (NAV-SAT) seen: %i, used: %i", sats_seen, sats_used
            )

        elif msg_class == "NAV-SOL":
            # only source of truth for satellites used in a FIX
            if "satellites" in msg:
                sats_used = msg["satellites"]
                sats[1] = sats_used
                gps_queue.put(("satellites", tuple(sats)))

            if all(k in msg for k in ["lat", "lon", "altHAE", "ecefpAcc", "mode"]):
                if not gps_locked and msg["ecefpAcc"] < MAX_GPS_ERROR:
                    gps_locked = True
                    console_queue.put("GPS: Locked")
                    logger.debug("GPS locked")
                gps_queue.put(
                    (
                        "fix",
                        {
                            "lat": msg["lat"],
                            "lon": msg["lon"],
                            "altitude": msg["altHAE"],
                            "source": "GPS",
                            "lock": gps_locked,
                            "lock_type": msg["mode"],
                            "error_in_m": msg["ecefpAcc"],
                        },
                    )
                )
                logger.debug("GPS fix: %s", msg)

        elif msg_class == "NAV-TIMEGPS":
            if "time" in msg and "valid" in msg and msg["valid"]:
                gps_queue.put(
                    (
                        "time",
                        {
                            "time": msg["time"],
                            "tAcc": msg["tAcc"] if "tAcc" in msg else -1,
                            "source": "GPS",
                        },
                    )
                )
            else:
                logger.debug(f"TIMEGPS message does not qualify: {msg}")

        elif msg_class == "NAV-PVT":
            if all(k in msg for k in ["lat", "lon", "altHAE", "hAcc", "vAcc"]):
                if not gps_locked and msg["hAcc"] < MAX_GPS_ERROR:
                    gps_locked = True
                    console_queue.put("GPS: Locked")
                    logger.info("GPS locked")
                gps_queue.put(
                    (
                        "fix",
                        {
                            "lat": msg["lat"],
                            "lon": msg["lon"],
                            "altitude": msg["altHAE"],
                            "source": "GPS",
                            "lock": gps_locked,
                            "lock_type": msg["mode"],
                            "error_in_m": msg["hAcc"],
                        },
                    )
                )
                logger.debug("GPS fix: %s", msg)

        await asyncio.sleep(0)


async def gps_main(gps_queue, console_queue, log_queue, inject_parser=None):
    MultiprocLogging.configurer(log_queue)
    logger.info("Using UBX GPS code")
    error_info = {"error_2d": 123_456, "error_3d": 123_456}

    while True:
        try:
            if inject_parser:  # dependency injection for testing, see gps_fake.py
                parser = inject_parser
            else:
                parser = await UBXParser.connect(log_queue, host="127.0.0.1", port=2947)
            await process_messages(parser, gps_queue, console_queue, error_info)
        except Exception as e:
            logger.error(f"Error in GPS monitor: {e}")
            await asyncio.sleep(5)


def gps_monitor(gps_queue, console_queue, log_queue):
    asyncio.run(gps_main(gps_queue, console_queue, log_queue))
