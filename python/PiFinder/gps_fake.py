#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for GPS related functions

"""

import asyncio
from multiprocessing import Queue
import os
import time
import datetime
import logging

from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.gps_ubx_parser import UBXParser
from PiFinder.gps_ubx import process_messages

logger = logging.getLogger("GPS.fake")

# Have a linear count-down in error, simulating a bad fix, that gets better

error_delta = 100  # 200 * 0.5 = 100 seconds
error_start = 7_000  # 100 km
lock_at = 6_000  # 1 km
fix_2d = 4_000  # m
fix_3d = 1_000  # m
error_stop = 200  # 10s meters


async def emit(f_path: str, gps_queue: Queue, console_queue: Queue, filename: str):
    parser = None
    try:
        parser = await UBXParser.from_file(file_path=f_path)
        error_info = {"error_2d": 123_456, "error_3d": 123_456}
        await process_messages(
            parser.parse_messages,
            gps_queue,
            console_queue,
            error_info,
            wait=0,
            info=filename,
        )
        while gps_queue.qsize() > 20:
            logger.error("GPS queue: %s", gps_queue.qsize())
            await asyncio.sleep(10)
    finally:
        if parser is not None:
            await parser.close()


# Have a linear count-down in error, simulating a bad fix, that gets better

error_delta = 100  # 200 * 0.5 = 100 seconds
error_start = 2_000  # 100 km
lock_at = 1_000  # 1 km
fix_2d = 500  # m
fix_3d = 200  # m
error_stop = 200  # 10s meters


def gps_monitor(gps_queue, console_queue, log_queue, file_name="test.ubx"):
    MultiprocLogging.configurer(log_queue)
    logger.warning("GPS fake started")
    time.sleep(5)

    try:
        dir = "../test_ubx/"
        f_path = os.path.join(dir, file_name)
        if os.path.isfile(f_path):
            logger.info(f"Read ubx from {f_path}")

            while True:
                logger.info(
                    "************************************************************************"
                )
                logger.info(
                    "************************************************************************"
                )
                logger.info(
                    "************************************************************************"
                )
                logger.info(f"******************************* {f_path}")
                logger.info("Queue size (approximate): %s", gps_queue.qsize())
                asyncio.run(emit(f_path, gps_queue, console_queue, file_name))

        logger.error("Simulating GPS data")
        # Simulate no fix at start, becoming better in error over time.
        error_in_m = error_start
        lock = False
        lock_type = None
        i = -1
        while True:
            i += 1
            time.sleep(0.5)
            fix = (
                "fix",
                {
                    "lat": 34.22,
                    "lon": -118.22,
                    "altitude": 22,
                    "source": "fakeGPS",
                    "error_in_m": error_in_m,
                    "lock": lock,
                    "lock_type": lock_type,
                },
            )
            gps_queue.put(fix)
            if error_in_m < lock_at:
                lock = True
                lock_type = 0
            if error_in_m < fix_2d:
                lock_type = 2
            if error_in_m < fix_3d:
                lock_type = 3
            if error_in_m >= error_stop:
                error_in_m -= error_delta

            tm = ("time", {"time": datetime.datetime.now()})
            gps_queue.put(tm)

            if (i % 20) == 0:
                i = 0
                logger.debug("GPS fake: %s", fix)
                logger.debug("GPD fake: %s", tm)
    except BaseException:
        logger.exception("GPS.fake: gps_monitor() aborted.")
        time.sleep(1)  # Give time for log to be written
