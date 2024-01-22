#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
    This module contains the shared state
    object.
"""
import time
import datetime
import pickle
import pytz
from PiFinder import config
import logging


class UIState:
    def __init__(self):
        self.__observing_list = []
        self.__history_list = []
        self.__active_list = []  # either observing or history
        self.__target = None
        self.__message_timeout = 0
        self.__hint_timeout = 0
        self.__show_fps = False

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

    def hint_timeout(self):
        return self.__hint_timeout

    def set_hint_timeout(self, v):
        self.__hint_timeout = v

    def show_fps(self):
        return self.__show_fps

    def set_show_fps(self, v: bool):
        self.__show_fps = v

    def set_active_list_to_observing_list(self):
        self.__active_list = self.__observing_list

    def active_list_is_history_list(self):
        return self.__active_list == self.__history_list

    def active_list_is_observing_list(self):
        return self.__active_list == self.__observing_list

    def set_active_list_to_history_list(self):
        self.__active_list = self.__history_list

    def set_target_to_active_list_index(self, index: int):
        self.__target = self.__active_list[index]

    def set_target_and_add_to_history(self, target):
        logging.debug("set_target_and_add_to_history")
        logging.debug(f"setting target to {target}")
        self.__target = target
        if len(self.__history_list) == 0:
            self.__history_list.append(self.__target)
        elif self.__history_list[-1] != self.__target:
            self.__history_list.append(self.__target)

    def push_object(self, target):
        self.set_target_and_add_to_history(target)
        self.set_active_list_to_history_list()

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


"""
Example shared_state object:

SharedStateObj(
    power_state=1,
    solve_state=True,
    solution={'RA': 22.86683471463411, 'Dec': 15.347716050003328, 'imu_pos': [171.39798541261814, 202.7646132036331, 358.2794741322842],
              'solve_time': 1695297930.5532792, 'cam_solve_time': 1695297930.5532837, 'Roll': 306.2951794424281, 'FOV': 10.200729425086111,
              'RMSE': 21.995567413046142, 'Matches': 12, 'Prob': 6.987725483613384e-13, 'T_solve': 15.00384000246413, 'RA_target': 22.86683471463411,
              'Dec_target': 15.347716050003328, 'T_extract': 75.79255499877036, 'Alt': None, 'Az': None, 'solve_source': 'CAM', 'constellation': 'Psc'},
    imu={'moving': False, 'move_start': 1695297928.69749, 'move_end': 1695297928.764207, 'pos': [171.39798541261814, 202.7646132036331, 358.2794741322842],
         'start_pos': [171.4009455613444, 202.76321535004726, 358.2587208386012], 'status': 3},
    location={'lat': 59.05139745, 'lon': 7.987654, 'altitude': 151.4, 'gps_lock': False, 'timezone': 'Europe/Stockholm', 'last_gps_lock': None},
    datetime=None,
    screen=<PIL.Image.Image image mode=RGB size=128x128 at 0xE693C910>,
    solve_pixel=[305.6970520019531, 351.9438781738281]
)
"""


class SharedStateObj:
    def __init__(self):
        self.__power_state = 1
        self.__solve_state = None
        self.__ui_state = None
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
        self.__screen = None
        self.__solve_pixel = config.Config().get_option("solve_pixel")

    def serialize(self, output_file):
        with open(output_file, "wb") as f:
            pickle.dump(self, f)

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

    def __repr__(self):
        # A simple representation showing key attributes (adjust as needed)
        return (
            f"SharedStateObj("
            f"power_state={self.__power_state}, "
            f"solve_state={self.__solve_state}, "
            f"UI_state={self.__ui_state})"
            f"solution={self.__solution}, "
            f"imu={self.__imu}, "
            f"location={self.__location}, "
            f"datetime={self.datetime()}, "
            f"screen={self.__screen}, "
            f"solve_pixel={self.__solve_pixel})"
        )

    def __str__(self):
        # A more human-friendly representation (adjust as needed)
        return (
            f"Shared State Object:\n"
            f"Power State: {self.__power_state}\n"
            f"Solve State: {self.__solve_state}\n"
            f"UI_state={self.__ui_state})"
            f"Solution: {self.__solution}\n"
            f"IMU: {self.__imu}\n"
            f"Location: {self.__location}\n"
            f"Date-Time: {self.datetime()}\n"
            f"Screen: {self.__screen}\n"
            f"Solve Pixel: {self.__solve_pixel}"
        )
