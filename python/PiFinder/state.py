#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
    This module contains the shared state
    object.
"""
import time
import datetime
import pytz


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
