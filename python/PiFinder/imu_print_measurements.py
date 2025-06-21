#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
For testing the IMU: Not for use by PiFinder main loop.
Prints the IMU measurements (based on imu_pi.py)
"""

import time
import board
import adafruit_bno055
#import logging

from scipy.spatial.transform import Rotation

#from PiFinder import config

#logger = logging.getLogger("IMU.pi")

QUEUE_LEN = 10
MOVE_CHECK_LEN = 2


class ImuSimple:
    def __init__(self):
        i2c = board.I2C()
        self.sensor = adafruit_bno055.BNO055_I2C(i2c)
        self.sensor.mode = adafruit_bno055.IMUPLUS_MODE
        # self.sensor.mode = adafruit_bno055.NDOF_MODE
        
        # Unlike Imu(), we use the IMU's native orientation
        self.quat_history = [(0, 0, 0, 0)] * QUEUE_LEN
        self._flip_count = 0
        self.calibration = 0
        self.avg_quat = (0, 0, 0, 0)
        self.__moving = False

        self.last_sample_time = time.time()

        # Calibration settings
        self.imu_sample_frequency = 1 / 30

        # First value is delta to exceed between samples
        # to start moving, second is threshold to fall below
        # to stop moving.
        self.__moving_threshold = (0.0005, 0.0003)

    def quat_to_euler(self, quat):
        """ 
        INPUTS:
        quat: Scalar last quaternion (x, y, z, w)

        OUTPUTS:
        rot_euler: [Az, related_to_roll, Alt]
        """
        if quat[0] + quat[1] + quat[2] + quat[3] == 0:
            return 0, 0, 0
        rot = Rotation.from_quat(quat)  # Expects scalar-last quaternion
        # Lowercase 'xyz' indicate extrinsic rotation:
        rot_euler = rot.as_euler("xyz", degrees=True)
        # convert from -180/180 to 0/360
        rot_euler[0] += 180
        rot_euler[1] += 180
        rot_euler[2] += 180
        return rot_euler

    def moving(self):
        """
        Compares most recent reading
        with past readings
        """
        return self.__moving

    def update(self):
        # check for update frequency
        if time.time() - self.last_sample_time < self.imu_sample_frequency:
            return

        self.last_sample_time = time.time()

        # Throw out non-calibrated data
        self.calibration = self.sensor.calibration_status[1]
        if self.calibration == 0:
            #logger.warning("NOIMU CAL")
            return True
        # adafruit_bno055 gives quaternion convention (w, x, y, z)
        quat = self.sensor.quaternion
        if quat[0] is None:
            #logger.warning("IMU: Failed to get sensor values")
            return

        _quat_diff = []
        for i in range(4):
            _quat_diff.append(abs(quat[i] - self.quat_history[-1][i]))

        self.__reading_diff = sum(_quat_diff)

        # This seems to be some sort of defect / side effect
        # of the integration system in the BNO055
        # When not moving quat output will vaccilate
        # by exactly this amount... so filter this out
        if self.__reading_diff == 0.0078125:
            self.__reading_diff = 0
            return

        # Sometimes the quat output will 'flip' and change by 2.0+
        # from one reading to another.  This is clearly noise or an
        # artifact, so filter them out
        if self.__reading_diff > 1.5:
            self._flip_count += 1
            if self._flip_count > 10:
                # with the history initialized to 0,0,0,0 the unit
                # can get stuck seeing flips if the IMU starts
                # returning data. This count will reset history
                # to the current state if it exceeds 10
                self.quat_history = [quat] * QUEUE_LEN
                self.__reading_diff = 0
            else:
                self.__reading_diff = 0
                return
        else:
            # no flip
            self._flip_count = 0

        self.avg_quat = quat
        if len(self.quat_history) == QUEUE_LEN:
            self.quat_history = self.quat_history[1:]
        self.quat_history.append(quat)

        if self.__moving:
            if self.__reading_diff < self.__moving_threshold[1]:
                self.__moving = False
        else:
            if self.__reading_diff > self.__moving_threshold[0]:
                self.__moving = True

    def get_euler(self):
        return list(self.quat_to_euler(self.avg_quat))  # !! Expect scalar-last but avg_quat is scalar-first??


def imu_monitor():
    #MultiprocLogging.configurer(log_queue)
    imu = ImuSimple()
    imu_calibrated = False
    imu_data = {
        "moving": False,
        "move_start": None,
        "move_end": None,
        "pos": [0, 0, 0],  # Corresponds to [Az, related_to_roll, Alt]
        "quat": [0, 0, 0, 0],  # Scalar-first quaternion (w, x, y, z)
        "start_pos": [0, 0, 0],
        "status": 0,
    }

    while True:
        imu.update()
        imu_data["status"] = imu.calibration
        if imu.moving():
            if not imu_data["moving"]:
                #logger.debug("IMU: move start")
                imu_data["moving"] = True
                imu_data["start_pos"] = imu_data["pos"]
                imu_data["move_start"] = time.time()
            imu_data["pos"] = imu.get_euler()
            imu_data["quat"] = imu.avg_quat

            print(imu_data["quat"])

        else:
            if imu_data["moving"]:
                # If we were moving and we now stopped
                #logger.debug("IMU: move end")
                imu_data["moving"] = False
                imu_data["pos"] = imu.get_euler()
                imu_data["quat"] = imu.avg_quat
                imu_data["move_end"] = time.time()

        if not imu_calibrated:
            if imu_data["status"] == 3:
                imu_calibrated = True
                #console_queue.put("IMU: NDOF Calibrated!")


if __name__ == "__main__":
    imu_monitor()
