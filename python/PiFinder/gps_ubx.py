#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions
"""

import asyncio
import time
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.gps_comms import CommsPublisher
from PiFinder.gps_ubx_parser import UBXParser
import logging

logger = logging.getLogger("GPS.parser")
sats = [0, 0]

MAX_GPS_ERROR = 50000  # 50 km

# How long a NAV-SAT message keeps NAV-SVINFO suppressed. NAV-SAT is the better
# source where a receiver emits it, but preferring it must not be a one-way
# latch: a receiver that sends NAV-SAT once (or intermittently) would otherwise
# silence the SVINFO fallback for the life of the connection and freeze the
# counts at whatever that last NAV-SAT said.
NAV_SAT_PREFERENCE_TIMEOUT = 5.0  # seconds


def _publish_sats(gps_queue, seen=None, used=None):
    """Publish the (seen, used) satellite counts, holding seen >= used.

    A satellite used in the navigation solution is by definition tracked, so a
    used count above the seen count is never physically meaningful. NAV-SOL and
    NAV-PVT carry only the used count; without this floor the status screen
    reads "0/9" until a NAV-SAT or NAV-SVINFO message supplies a seen count.
    """
    if seen is not None:
        sats[0] = seen
    if used is not None:
        sats[1] = used
    if sats[0] < sats[1]:
        sats[0] = sats[1]
    gps_queue.put(("satellites", tuple(sats)))


async def process_messages(
    parser_iterator,
    gps_queue,
    console_queue,
    error_info,
    wait=0,
    info=None,
    clock=time.monotonic,
):
    gps_locked = False
    last_nav_sat = None  # monotonic stamp of the most recent NAV-SAT message
    comms = CommsPublisher(gps_queue, clock=clock)

    async for msg in parser_iterator():
        msg_class = msg.get("class", "")
        logger.debug("GPS: %s: %s", msg_class, msg)

        # One reading per event, shared by everything below, so the comms
        # stamp and the NAV-SAT freshness window agree on when this arrived.
        now = clock()

        # Every event counts towards liveness, including markers and messages
        # the dispatch chain below has no branch for.
        comms.publish(msg_class, now)

        if msg_class == "NAV-DOP":
            error_info["error_2d"] = msg["hdop"]
            error_info["error_3d"] = msg["pdop"]

        elif msg_class == "NAV-SVINFO":
            # Fallback satellite info, used while NAV-SAT is absent or stale
            nav_sat_fresh = (
                last_nav_sat is not None
                and now - last_nav_sat < NAV_SAT_PREFERENCE_TIMEOUT
            )
            if not nav_sat_fresh and "nSat" in msg:
                sats_seen = msg["nSat"]
                sats_used = msg["uSat"]
                _publish_sats(gps_queue, seen=sats_seen, used=sats_used)
                logger.debug(
                    "Number of sats (SVINFO) seen: %i, used: %i", sats_seen, sats_used
                )

        elif msg_class == "NAV-SAT":
            # Preferred satellite info source - not seen in the current pifinder gps versions
            last_nav_sat = now
            sats_seen = msg["nSat"]
            sats_used = sum(
                1 for sat in msg.get("satellites", []) if sat.get("used", False)
            )
            _publish_sats(gps_queue, seen=sats_seen, used=sats_used)
            logger.debug(
                "Number of sats (NAV-SAT) seen: %i, used: %i", sats_seen, sats_used
            )

        elif msg_class == "NAV-SOL":
            # only source of truth for satellites used in a FIX
            if "satellites" in msg:
                _publish_sats(gps_queue, used=msg["satellites"])

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
                            "source": "GPS" if not info else info,
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
                            "source": "GPS" if not info else info,
                        },
                    )
                )
            else:
                logger.debug(f"TIMEGPS message does not qualify: {msg}")

        elif msg_class == "NAV-PVT":
            if "numSV" in msg:
                _publish_sats(gps_queue, used=msg["numSV"])
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

        # Wait a bit more on processing, if messages pile up in the queue
        if gps_queue.qsize() > 50:
            await asyncio.sleep(0.7)
        elif gps_queue.qsize() > 10:
            await asyncio.sleep(0.1)
        await asyncio.sleep(wait)


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
            await process_messages(
                parser.parse_messages, gps_queue, console_queue, error_info
            )
        except Exception as e:
            logger.error(f"Error in GPS monitor: {e}")
            await asyncio.sleep(5)


def gps_monitor(gps_queue, console_queue, log_queue):
    asyncio.run(gps_main(gps_queue, console_queue, log_queue))
