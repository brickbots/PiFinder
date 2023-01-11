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
        self.__solve_state = None
        self.__last_image_time = (0, 0)
        self.__solution = None
        self.__imu = None
        self.__location = None
        self.__datetime = None
        self.__datetime_time = None
        self.__target = None

    def target(self):
        return self.__target

    def set_target(self, target):
        self.__target = target

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

    def last_image_time(self):
        return self.__last_image_time

    def set_last_image_time(self, v):
        self.__last_image_time = v

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
        utc_tz = pytz.timezone("UTC")
        dt = utc_tz.localize(dt)
        return dt.astimezone(pytz.timezone(self.__location["timezone"]))

    def set_datetime(self, dt):
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
