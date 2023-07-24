#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for IMU related functions

"""
from pprint import pprint
import time
import board
import adafruit_bno055

from scipy.spatial.transform import Rotation

from PiFinder import config

QUEUE_LEN = 10
MOVE_CHECK_LEN = 2


class Imu:
    def __init__(self):
        i2c = board.I2C()
        self.sensor = adafruit_bno055.BNO055_I2C(i2c)
        # self.sensor.mode = adafruit_bno055.IMUPLUS_MODE
        self.sensor.mode = adafruit_bno055.NDOF_MODE
        cfg = config.Config()
        if cfg.get_option("screen_direction") == "flat":
            self.sensor.axis_remap = (
                adafruit_bno055.AXIS_REMAP_Y,
                adafruit_bno055.AXIS_REMAP_X,
                adafruit_bno055.AXIS_REMAP_Z,
                adafruit_bno055.AXIS_REMAP_POSITIVE,
                adafruit_bno055.AXIS_REMAP_POSITIVE,
                adafruit_bno055.AXIS_REMAP_NEGATIVE,
            )
        else:
            self.sensor.axis_remap = (
                adafruit_bno055.AXIS_REMAP_Z,
                adafruit_bno055.AXIS_REMAP_Y,
                adafruit_bno055.AXIS_REMAP_X,
                adafruit_bno055.AXIS_REMAP_POSITIVE,
                adafruit_bno055.AXIS_REMAP_POSITIVE,
                adafruit_bno055.AXIS_REMAP_POSITIVE,
            )
        self.quat_history = [(0, 0, 0, 0)] * QUEUE_LEN
        self.__moving = False
        self.__moving_threshold = (0.005, 0.001)
        self.calibration = 0
        self.avg_quat = (0, 0, 0, 0)

    def quat_to_euler(self, quat):
        if quat[0] + quat[1] + quat[2] + quat[3] == 0:
            return 0, 0, 0
        rot = Rotation.from_quat(quat)
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
        # Throw out non-calibrated data
        self.calibration = self.sensor.calibration_status[1]
        if self.calibration == 0:
            return True
        quat = self.sensor.quaternion
        if quat[0] == None:
            print("IMU: Failed to get sensor values")
            return

        self.__reading_diff = (
            abs(quat[0] - self.quat_history[-1][0])
            + abs(quat[1] - self.quat_history[-1][1])
            + abs(quat[2] - self.quat_history[-1][2])
            + abs(quat[3] - self.quat_history[-1][3])
        )

        if self.__reading_diff > 1.5:
            # FLIP, just ignore
            return

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
        return list(self.quat_to_euler(self.avg_quat))


def imu_monitor(shared_state, console_queue):
    imu = Imu()
    imu_calibrated = False
    imu_data = {
        "moving": False,
        "move_start": None,
        "move_end": None,
        "pos": None,
        "start_pos": None,
        "status": 0,
    }
    while True:
        imu.update()
        imu_data["status"] = imu.calibration
        if imu.moving():
            if imu_data["moving"] == False:
                # print("IMU: move start")
                imu_data["moving"] = True
                imu_data["start_pos"] = imu_data["pos"]
                imu_data["move_start"] = time.time()
            imu_data["pos"] = imu.get_euler()
        else:
            if imu_data["moving"] == True:
                # If wer were moving and we now stopped
                # print("IMU: move end")
                imu_data["moving"] = False
                imu_data["pos"] = imu.get_euler()
                imu_data["move_end"] = time.time()

        if imu_calibrated == False:
            if imu_data["status"] == 3:
                imu_calibrated = True
                console_queue.put("IMU: NDOF Calibrated!")

        if shared_state != None and imu_calibrated:
            shared_state.set_imu(imu_data)
