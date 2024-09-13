#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions
"""
import asyncio
from PiFinder.multiproclogging import MultiprocLogging
from gpsdclient import GPSDClient
import logging

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


async def sky_messages(client, gps_queue):
    async for result in client.dict_stream(convert_datetime=True, filter=["SKY"]):
        if result["class"] == "SKY" and "nSat" in result:
            sats_seen = result["nSat"]
            sats_used = result["uSat"]
            num_sats = (sats_seen, sats_used)
            msg = ("satellites", num_sats)
            logger.debug("Number of sats seen: %i", sats_seen)
            await gps_queue.put(msg)


async def reading_messages(client, gps_queue, console_queue, gps_locked):
    async for result in client.dict_stream(convert_datetime=True, filter=["TPV"]):
        if is_tpv_accurate(result):
            logger.debug("last reading is %s", result)
            if result.get("lat") and result.get("lon") and result.get("altHAE"):
                if not gps_locked:
                    gps_locked = True
                    await console_queue.put("GPS: Locked")
                    logger.debug("GPS locked")
                msg = (
                    "fix",
                    {
                        "lat": result.get("lat"),
                        "lon": result.get("lon"),
                        "altitude": result.get("altHAE"),
                    },
                )
                logger.debug("GPS fix: %s", msg)
                await gps_queue.put(msg)

            if result.get("time"):
                msg = ("time", result.get("time"))
                logger.debug("Setting time to %s", result.get("time"))
                await gps_queue.put(msg)


async def gps_main(gps_queue, console_queue, log_queue):
    MultiprocLogging.configurer(log_queue)
    gps_locked = False

    while True:
        try:
            with GPSDClient(host="127.0.0.1") as client:
                while True:
                    logger.debug("GPS waking")

                    # Run both async functions concurrently
                    await asyncio.gather(
                        sky_messages(client, gps_queue),
                        reading_messages(client, gps_queue,
                                         console_queue, gps_locked)
                    )

                    logger.debug("GPS sleeping now for 7s")
                    await asyncio.sleep(7)
        except Exception as e:
            logger.error(f"Error in GPS monitor: {e}")
            await asyncio.sleep(5)  # Wait before attempting to reconnect


# To run the GPS monitor
def gps_monitor(gps_queue, console_queue, log_queue):
    asyncio.run(gps_main(gps_queue, console_queue, log_queue))
