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


class Imu:
    def __init__(self):
        i2c = board.I2C()
        self.sensor = adafruit_bno055.BNO055_I2C(i2c)
        # self.sensor.mode = adafruit_bno055.IMUPLUS_MODE
        self.quat_history = [(0, 0, 0, 0)] * 10
        self.flip_count = 0
        self.avg_quat = (0, 0, 0, 0)
        self.__moving = False
        self.calibration = 0

    def quat_to_euler(self, quat):
        if quat[0] + quat[1] + quat[2] + quat[3] == 0:
            return 0, 0, 0
        rot = Rotation.from_quat(quat)
        rot_euler = rot.as_euler("xyz", degrees=True)
        return rot_euler

    def moving(self):
        """
        Compares most recent reading
        with past readings
        """
        return self.__moving

    def flip(self, quat):
        """
        Compares most recent reading
        with past readings and find
        and filter anomolies
        """
        if len(self.quat_history) < 10:
            return False

        dif = (
            abs(quat[0] - self.quat_history[-1][0])
            + abs(quat[1] - self.quat_history[-1][1])
            + abs(quat[2] - self.quat_history[-1][2])
            + abs(quat[3] - self.quat_history[-1][3])
        )
        if dif > 0.1:
            self.flip_count += 1
            if self.flip_count > 10:
                return False
            return True
        else:
            self.flip_count = 0
            return False

    def update(self):
        # Throw out non-calibrated data
        self.calibration = self.sensor.calibration_status[0]
        if self.calibration == 0:
            return True
        quat = self.sensor.quaternion

        # update moving
        if not self.flip(quat):
            dif = (
                abs(quat[0] - self.avg_quat[0])
                + abs(quat[1] - self.avg_quat[1])
                + abs(quat[2] - self.avg_quat[2])
                + abs(quat[3] - self.avg_quat[3])
            )
            if dif > 0.01:
                self.__moving = True
            else:
                self.__moving = False

            # add to averages
            if len(self.quat_history) == 10:
                self.quat_history = self.quat_history[1:]
            self.quat_history.append(quat)
            self.calc_avg_quat()

    def calc_avg_quat(self):
        quat = [0, 0, 0, 0]
        for q in self.quat_history:
            quat[0] += q[0]
            quat[1] += q[1]
            quat[2] += q[2]
            quat[3] += q[3]

        self.avg_quat = (
            quat[0] / 10,
            quat[1] / 10,
            quat[2] / 10,
            quat[3] / 10,
        )

    def get_euler(self):
        return self.quat_to_euler(self.avg_quat)


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
                print("IMU: move start")
                imu_data["moving"] = True
                imu_data["start_pos"] = imu_data["pos"]
                imu_data["move_start"] = time.time()
                # pprint(imu_data)
            imu_data["pos"] = imu.get_euler()
            # print(imu_data["pos"], imu_data["status"])
            if shared_state != None:
                shared_state.set_imu(imu_data)
        else:
            if imu_data["moving"] == True:
                # If wer were moving and we now stopped
                print("IMU: move end")
                imu_data["moving"] = False
                imu_data["pos"] = imu.get_euler()
                imu_data["move_end"] = time.time()
                # pprint(imu_data)
                if shared_state != None:
                    shared_state.set_imu(imu_data)
        if imu_calibrated == False:
            if imu_data["status"] == 3:
                imu_calibrated = True
                console_queue.put("IMU: NDOF Calibrated!")
