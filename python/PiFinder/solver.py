#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the solver
* Checks IMU
* Plate solves high-res image

"""
import queue
import pprint
import time
from tetra3 import Tetra3
from skyfield.api import (
    wgs84,
    load,
    utc,
    Star,
    Angle,
    position_of_radec,
    load_constellation_map,
)


class Skyfield_utils:
    """
    Class to persist various
    expensive items that
    skyfield requires (ephemeris, constellations, etc)
    and provide useful util functions using them.
    """

    def __init__(self):
        self.eph = load("de421.bsp")
        self.earth = self.eph["earth"]
        self.observer_loc = None
        self.constellation_map = load_constellation_map()

    def set_location(self, lat, lon, altitude):
        """
        set observing location
        """
        self.observer_loc = self.earth + wgs84.latlon(
            lat,
            lon,
            altitude,
        )

    def radec_to_altaz(self, ra, dec, dt):
        """
        returns the apparent ALT/AZ of a specfic
        RA/DEC at the given time
        """
        dt = dt.replace(tzinfo=utc)
        ts = load.timescale()
        t = ts.from_datetime(dt)

        observer = self.observer_loc.at(t)
        sky_pos = Star(
            ra=Angle(degrees=ra),
            dec_degrees=dec,
        )

        apparent = observer.observe(sky_pos).apparent()
        alt, az, distance = apparent.altaz("standard")
        return alt.degrees, az.degrees

    def radec_to_constellation(self, ra, dec):
        """
        Take a ra/dec and return the constellation
        """
        sky_pos = position_of_radec(Angle(degrees=ra)._hours, dec)
        return self.constellation_map(sky_pos)


def solver(shared_state, camera_image, console_queue):
    sf_utils = Skyfield_utils()
    t3 = Tetra3("default_database")
    last_image_fetch = 0
    while True:
        last_image_time = shared_state.last_image_time()
        if last_image_time > last_image_fetch:
            solve_image = camera_image.copy()
            solved = t3.solve_from_image(
                solve_image,
                fov_estimate=10.2,
                fov_max_error=0.1,
            )
            if solved["RA"] != None:
                solved["solve_time"] = time.time()
                solved["constellation"] = sf_utils.radec_to_constellation(
                    solved["RA"], solved["Dec"]
                )
                # see if we can calc alt-az
                solved["alt"] = None
                solved["az"] = None
                location = shared_state.location()
                dt = shared_state.datetime()
                if location and dt:
                    # We have position and time/date!
                    sf_utils.set_location(
                        location["lat"],
                        location["lon"],
                        location["altitude"],
                    )
                    alt, az = sf_utils.radec_to_altaz(
                        solved["RA"],
                        solved["Dec"],
                        dt,
                    )
                    solved["Alt"] = alt
                    solved["Az"] = az
                shared_state.set_solution(solved)
                shared_state.set_solve_state(True)

            last_image_fetch = last_image_time
