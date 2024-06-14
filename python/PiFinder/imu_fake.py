#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for IMU related functions

"""

import time


QUEUE_LEN = 50
AVG_LEN = 2
MOVE_CHECK_LEN = 10


class Imu:
    def __init__(self):
        pass

    def moving(self):
        """
        Compares most recent reading
        with past readings
        """
        return self.moving

    def flip(self, quat):
        """
        Compares most recent reading
        with past readings and find
        and filter anomolies
        """
        return self.flip

    def update(self):
        # Throw out non-calibrated data
        pass


def imu_monitor(shared_state, console_queue):
    imu = Imu()
    while True:
        imu.update()
        time.sleep(0.1)
