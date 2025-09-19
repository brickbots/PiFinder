#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for IMU related functions

"""

import time

from PiFinder.multiproclogging import MultiprocLogging


QUEUE_LEN = 50
AVG_LEN = 2
MOVE_CHECK_LEN = 10


class Imu:
    """A fake IMU class for testing without hardware
    This class mimics the interface of the real IMU class, but does not read from actual hardware.
    It _is_ used in the real IMU class, in case the physical IMU is not available.
    """

    def __init__(self):
        self._moving = False
        self._flip = False
        pass

    def moving(self):
        """
        Compares most recent reading
        with past readings
        """
        return self._moving

    def flip(self, quat):
        """
        Compares most recent reading
        with past readings and find
        and filter anomolies
        """
        return self._flip

    def update(self):
        # Sleep to not comsume too much CPU, this also needs to be done, as the real IMU needs time to get new readings
        time.sleep(0.1)
        pass


def imu_monitor(shared_state, console_queue, log_queue):
    MultiprocLogging.configurer(log_queue)
    imu = Imu()
    while True:
        imu.update()
