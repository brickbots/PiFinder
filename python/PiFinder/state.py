#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
    This module contains the shared state
    object.
"""
import time
import datetime
import pytz
from PiFinder import config


class UIState:
    def __init__(self):
        self.__observing_list = []
        self.__history_list = []
        self.__active_list = []
        self.__target = None
        self.__message_timeout = 0

    def observing_list(self):
        return self.__observing_list

    def set_observing_list(self, v):
        self.__observing_list = v

    def history_list(self):
        return self.__history_list

    def set_history_list(self, v):
        self.__history_list = v

    def active_list(self):
        return self.__active_list

    def set_active_list(self, v):
        self.__active_list = v

    def target(self):
        return self.__target

    def set_target(self, v):
        self.__target = v

    def message_timeout(self):
        return self.__message_timeout

    def set_message_timeout(self, v):
        self.__message_timeout = v

    def set_active_list_to_observing_list(self):
        self.__active_list = self.__observing_list

    def active_list_is_history_list(self):
        return self.__active_list == self.__history_list

    def set_active_list_to_history_list(self):
        self.__active_list = self.__history_list

    def set_target_to_active_list_index(self, index: int):
        self.__target = self.__active_list[index]

    def set_target_and_add_to_history(self, target):
        print("set_target_and_add_to_history")
        print(f"setting target to {target}")
        self.__target = target
        if len(self.__history_list) == 0:
            self.__history_list.append(self.__target)
        elif self.__history_list[-1] != self.__target:
            self.__history_list.append(self.__target)

    def __str__(self):
        return str(
            {
                "observing_list": self.__observing_list,
                "history_list": self.__history_list,
                "active_list": self.__active_list,
                "target": self.__target,
                "message_timeout": self.__message_timeout,
            }
        )

    def __repr__(self):
        return self.__str__()


class SharedStateObj:
    def __init__(self):
        self.__power_state = 1
        self.__solve_state = None
        self.__last_image_metadata = {
            "exposure_start": 0,
            "exposure_end": 0,
            "imu": None,
            "imu_delta": 0,
        }
        self.__solution = None
        self.__imu = None
        self.__location = None
        self.__datetime = None
        self.__datetime_time = None
        self.__target = None
        self.__screen = None
        self.__ui_state = None
        self.__solve_pixel = config.Config().get_option("solve_pixel")

    def solve_pixel(self, screen_space=False):
        """
        solve_pixel is (Y,X) in camera image (512x512) space

        if screen_space=True, this is returned as (X,Y) in screen (128x128) space
        """
        if screen_space:
            return (int(self.__solve_pixel[1] / 4), int(self.__solve_pixel[0] / 4))
        return self.__solve_pixel

    def set_solve_pixel(self, coords):
        self.__solve_pixel = coords

    def power_state(self):
        return self.__power_state

    def set_power_state(self, v):
        self.__power_state = v

    def solve_state(self):
        return self.__solve_state

    def set_solve_state(self, v):
        self.__solve_state = v

    def imu(self):
        return self.__imu

    def set_imu(self, v):
        self.__imu = v

    def solution(self):
        return self.__solution

    def set_solution(self, v):
        self.__solution = v

    def location(self):
        return self.__location

    def set_location(self, v):
        self.__location = v

    def last_image_metadata(self):
        return self.__last_image_metadata

    def set_last_image_metadata(self, v):
        self.__last_image_metadata = v

    def datetime(self):
        if self.__datetime == None:
            return self.__datetime
        return self.__datetime + datetime.timedelta(
            seconds=time.time() - self.__datetime_time
        )

    def local_datetime(self):
        if self.__datetime == None:
            return self.__datetime

        if not self.__location:
            return self.datetime()

        dt = self.datetime()
        return dt.astimezone(pytz.timezone(self.__location["timezone"]))

    def set_datetime(self, dt):
        if dt.tzname() == None:
            utc_tz = pytz.timezone("UTC")
            dt = utc_tz.localize(dt)

        if self.__datetime == None:
            self.__datetime_time = time.time()
            self.__datetime = dt
        else:
            # only reset if there is some significant diff
            # as some gps recievers send multiple updates that can
            # rewind and fastforward the clock
            curtime = self.__datetime + datetime.timedelta(
                seconds=time.time() - self.__datetime_time
            )
            if curtime > dt:
                diff = (curtime - dt).seconds
            else:
                diff = (dt - curtime).seconds
            if diff > 60:
                self.__datetime_time = time.time()
                self.__datetime = dt

    def screen(self):
        return self.__screen

    def set_screen(self, v):
        self.__screen = v

    def ui_state(self):
        return self.__ui_state

    def set_ui_state(self, v):
        self.__ui_state = v

    def __str__(self):
        return str(
            {
                "power_state": self.__power_state,
                "solve_state": self.__solve_state,
                "last_image_metadata": self.__last_image_metadata,
                "solution": self.__solution,
                "imu": self.__imu,
                "location": self.__location,
                "datetime": self.__datetime,
                "target": self.__target,
                "screen": self.__screen,
                "ui_state": self.__ui_state,
            }
        )

    def __repr__(self):
        return self.__str__()
