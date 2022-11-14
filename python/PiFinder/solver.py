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
from skyfield.api import wgs84, load, utc, Star, Angle
from skyfield.positionlib import position_of_radec


def radec_to_altaz(ra, dec, lat, lon, altitude, dt):
    """
    returns the apparent ALT/AZ of a specfic
    RA/DEC at the given location/time
    """
    dt = dt.replace(tzinfo=utc)
    ts = load.timescale()
    t = ts.from_datetime(dt)

    eph = load("de421.bsp")
    earth = eph["earth"]
    observer_loc = earth + wgs84.latlon(
        lat,
        lon,
        altitude,
    )
    observer = observer_loc.at(t)
    sky_pos = Star(
        ra=Angle(degrees=ra),
        dec_degrees=dec,
    )

    apparent = observer.observe(sky_pos).apparent()
    alt, az, distance = apparent.altaz()
    return alt, az


def solver(shared_state, camera_image, console_queue):
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
            if solved["ra"] != None:
                # see if we can calc alt-az
                solved["alt"] = None
                solved["az"] = None
                location = shared_state.location()
                if location:
                    dt = shared_state.datetime()
                    if dt:
                        # We have position and time/date!
                        alt, az = radec_to_altaz(
                            solved["ra"],
                            solved["dec"],
                            location["lat"],
                            location["lon"],
                            location["altitude"],
                            dt,
                        )
                        solved["alt"] = alt
                        solved["az"] = az
                shared_state.set_solve(solved)

            last_image_fetch = last_image_time
