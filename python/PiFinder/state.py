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
from typing import List
from PiFinder.composite_object import CompositeObject
from typing import Optional
from dataclasses import dataclass, asdict
import json
from timezonefinder import TimezoneFinder

logger = logging.getLogger("SharedState")


class RecentCompositeObjectList(list):
    """keeps the recent list of composite_objects,
    handling duplicates"""

    def __init__(self):
        super().__init__()

    def append(self, item: CompositeObject) -> None:
        # Remove the item if it's already in the list
        try:
            super().remove(item)
        except ValueError:
            pass

        # Add the item to the end of the list
        super().append(item)

    def __iter__(self):
        return super().__iter__()

    def __repr__(self) -> str:
        return f"RecentList({super().__repr__()})"

    def __str__(self) -> str:
        return super().__str__()


class UIState:
    def __init__(self):
        self.__observing_list = []
        self.__recent = RecentCompositeObjectList()
        self.__target = None
        self.__message_timeout = 0
        self.__hint_timeout = 0
        self.__show_fps = False
        # Set to true when an object is pushed
        # to the recent list from the pos_server
        # proccess (i.e. skysafari goto).  Used
        # to jump from object list to object details
        self.__new_pushto = False

    def observing_list(self):
        return self.__observing_list

    def set_observing_list(self, v):
        self.__observing_list = v

    def recent_list(self) -> List[CompositeObject]:
        return list(reversed(self.__recent))

    def add_recent(self, v: CompositeObject):
        self.__recent.append(v)

    def set_new_pushto(self, v: bool):
        self.__new_pushto = v

    def new_pushto(self) -> bool:
        return self.__new_pushto

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

    def __str__(self):
        return str(
            {
                "recent": self.__recent,
                "hint_timeout": self.__hint_timeout,
                "show_fps": self.__show_fps,
                "observing_list": self.__observing_list,
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
    location={'lat': 59.05139745, 'lon': 7.987654, 'altitude': 151.4, 'source': 'GPS', gps_lock': False, 'timezone': 'Europe/Stockholm', 'last_gps_lock': None},
    datetime=None,
    screen=<PIL.Image.Image image mode=RGB size=128x128 at 0xE693C910>,
    solve_pixel=[305.6970520019531, 351.9438781738281]
)
"""


@dataclass
class Location:
    """
    the location of the observer, lat/lon/altitude and the source of the data.
    """

    lat: float = 0.0
    lon: float = 0.0
    altitude: float = 0.0
    source: str = "None"
    lock: bool = False  # lock means: we received a good enough location, not a GPS Fix
    lock_type: int = 0  # limited, basic, accurate, precise
    error_in_m: float = 0.0
    timezone: Optional[str] = "UTC"
    last_gps_lock: Optional[str] = None

    def __str__(self):
        return (
            f"Location(lat={self.lat:.6f}, "
            f"lon={self.lon:.6f}, "
            f"alt={self.altitude:.1f}m, "
            f"source={self.source}, "
            f"error={self.error_in_m:.1f}m, "
            f"lock={'Yes' if self.lock else 'No'} "
            f"lock_type={self.lock_type}, "
            f"{f', tz={self.timezone}' if self.timezone else ''}"
            f"{f', last_lock={self.last_gps_lock}' if self.last_gps_lock else ''})"
        )

    def reset(self):
        self.lat = 0.0
        self.lon = 0.0
        self.altitude = 0.0
        self.source = "None"
        self.lock = False
        self.lock_type = 0
        self.error_in_m = 0
        self.timezone = "UTC"
        self.last_gps_lock = None

    def to_dict(self):
        """Convert the Location object to a dictionary."""
        return asdict(self)

    def to_json(self):
        """Convert the Location object to a JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data):
        """Create a Location object from a dictionary."""
        return cls(**data)

    @classmethod
    def from_json(cls, json_str):
        """Create a Location object from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)


@dataclass
class SQM:
    """
    Represents the sky brightness (SQM) value and its source.
    """

    value: float = 20.15  # Standard value set to 20.15
    source: str = "None"
    last_update: Optional[str] = None

    def __str__(self):
        return (
            f"SQM(value={self.value:.2f}, "
            f"source={self.source}, "
            f"last_update={self.last_update})"
        )

    def reset(self):
        self.value = 0.0
        self.source = "None"
        self.last_update = None

    def to_dict(self):
        """Convert the SQM object to a dictionary."""
        return asdict(self)

    def to_json(self):
        """Convert the SQM object to a JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data):
        """Create a SQM object from a dictionary."""
        return cls(**data)

    @classmethod
    def from_json(cls, json_str):
        """Create a SQM object from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)


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
        self.__sats = None
        self.__imu = None
        self.__location: Location = Location()
        self.__sqm: SQM = SQM()
        self.__datetime = None
        self.__datetime_time = None
        self.__screen = None
        self.__solve_pixel = config.Config().get_option("solve_pixel")
        self.__arch = None
        self.__camera_align = False
        # Are we prepared to do alt/az math
        # We need gps lock and datetime
        self.__tz_finder = TimezoneFinder()

    def serialize(self, output_file):
        with open(output_file, "wb") as f:
            pickle.dump(self, f)

    def altaz_ready(self):
        return bool(self.__location.lock and self.datetime())

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

    def arch(self):
        return self.__arch

    def set_arch(self, v):
        self.__arch = v

    def solve_state(self):
        return self.__solve_state

    def set_solve_state(self, v):
        self.__solve_state = v

    def camera_align(self):
        return self.__camera_align

    def set_camera_align(self, v: bool):
        self.__camera_align = v

    def sats(self):
        return self.__sats

    def set_sats(self, v):
        self.__sats = v

    def imu(self):
        return self.__imu

    def set_imu(self, v):
        self.__imu = v

    def solution(self):
        return self.__solution

    def set_solution(self, v):
        self.__solution = v

    def location(self):
        """Return the current location"""
        return self.__location

    def set_location(self, v):
        # if value is not none, set the timezone
        # before saving the value
        if v:
            v.timezone = self.__tz_finder.timezone_at(lat=v.lat, lng=v.lon)
        self.__location = v

    def sqm(self):
        """Return the current SQM object"""
        return self.__sqm

    def set_sqm(self, sqm: SQM):
        self.__sqm = sqm

    def last_image_metadata(self):
        return self.__last_image_metadata

    def set_last_image_metadata(self, v):
        self.__last_image_metadata = v

    def datetime(self):
        if self.__datetime is None:
            return self.__datetime
        return self.__datetime + datetime.timedelta(
            seconds=time.time() - self.__datetime_time
        )

    def local_datetime(self):
        if self.__datetime is None:
            return self.__datetime

        dt = self.datetime()
        if self.__location and self.__location.timezone:
            try:
                return dt.astimezone(pytz.timezone(self.__location.timezone))
            except (pytz.exceptions.UnknownTimeZoneError, AttributeError):
                # Fall back to UTC if timezone is invalid or None
                return dt.astimezone(pytz.timezone("UTC"))
        return dt.astimezone(pytz.timezone("UTC"))

    def set_datetime(self, dt):
        if dt.tzname() is None:
            utc_tz = pytz.timezone("UTC")
            dt = utc_tz.localize(dt)

        if self.__datetime is None:
            self.__datetime_time = time.time()
            self.__datetime = dt
        else:
            # only reset if there is some significant diff
            # as some gps recievers send multiple updates that can
            # rewind and fastforward the clock
            curtime = self.__datetime + datetime.timedelta(
                seconds=time.time() - self.__datetime_time
            )
            if curtime < dt:
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

    def get_sky_brightness(self):
        """
        Returns the current sky brightness (SQM) value from the shared state.
        """
        return self.__sqm.value

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
