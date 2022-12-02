#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the solver
* Checks IMU
* Plate solves high-res image

"""
import os
import queue
import pprint
import time
import copy
import uuid
import json
import gc

from PIL import ImageOps
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

from image_util import subtract_background

IMU_ALT = 2
IMU_AZ = 0

# Clean up what might be garbage so far.
gc.collect(2)
# Exclude current items from future GC.
gc.freeze()
#
allocs, gen1, gen2 = gc.get_threshold()
allocs = 50_000  # Start the GC sequence every 50K not 700 allocations.
gen1 = gen1 * 2
gen2 = gen2 * 2
gc.set_threshold(allocs, gen1, gen2)


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

    def altaz_to_radec(self, alt, az, dt):
        """
        returns the ra/dec of a specfic
        apparent alt/az at the given time
        """
        dt = dt.replace(tzinfo=utc)
        ts = load.timescale()
        t = ts.from_datetime(dt)

        observer = self.observer_loc.at(t)
        a = observer.from_altaz(alt_degrees=alt, az_degrees=az)
        ra, dec, distance = a.radec(epoch=t)
        return ra._degrees, dec._degrees

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


def write_debug(
    prefix, console_queue, image, last_solution, current_solution, location, imu, dt
):
    """
    Writes the image + key solver
    info to disk
    """
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    debug_path = os.path.join(root_dir, "solver_debug_dumps", prefix)

    # write images
    image.save(f"{debug_path}_raw.png")
    image = subtract_background(image)
    image = image.convert("RGB")
    image = ImageOps.autocontrast(image)
    image.save(f"{debug_path}_sub.png")

    with open(f"{debug_path}_newsolve.json", "w") as f:
        json.dump(current_solution, f, indent=4)

    with open(f"{debug_path}_oldsolve.json", "w") as f:
        json.dump(last_solution, f, indent=4)

    with open(f"{debug_path}_location.json", "w") as f:
        json.dump(location, f, indent=4)

    with open(f"{debug_path}_imu.json", "w") as f:
        json.dump(imu, f, indent=4)

    with open(f"{debug_path}_datetime.json", "w") as f:
        json.dump(dt.isoformat(), f, indent=4)

    console_queue.put(f"SLV: Debug {prefix}")


def solver(shared_state, camera_image, console_queue):
    debug_prefix = str(uuid.uuid1()).split("-")[0]
    debug_index = 0
    debug_solve = None
    sf_utils = Skyfield_utils()
    t3 = Tetra3("default_database")
    last_solve_time = 0
    imu_moving = False
    solved = {
        "RA": None,
        "Dec": None,
        "imu_pos": None,
        "Alt": None,
        "Az": None,
        "solve_source": None,
        "solve_time": None,
        "cam_solve_time": 0,
        "constellation": None,
        "last_image_solve": None,
    }

    # This holds the last image solve position info
    # so we can delta for IMU updates
    last_image_solve = None
    while True:
        # use the time the exposure started here to
        # reject images startede before the last solve
        # which might be from the IMU
        last_image_time = shared_state.last_image_time()[0]
        if last_image_time > last_solve_time:
            solve_image = camera_image.copy()
            new_solve = t3.solve_from_image(
                solve_image,
                fov_estimate=10.2,
                fov_max_error=0.1,
            )
            if new_solve["RA"] != None and solved["solve_source"] == "IMU":
                # we were on IMU, now we are back
                # to image solve. Check if we have really moved...
                if (
                    abs(new_solve["RA"] - last_image_solve["RA"])
                    + abs(new_solve["Dec"] - last_image_solve["Dec"])
                    > 10
                ):
                    debug_solve = copy.copy(solved)

            solved |= new_solve
            if solved["RA"] != None:
                imu = shared_state.imu()
                location = shared_state.location()
                dt = shared_state.datetime()

                if imu:
                    solved["imu_pos"] = imu["pos"]
                else:
                    solved["imu_pos"] = None
                solved["solve_time"] = time.time()
                solved["cam_solve_time"] = time.time()
                solved["solve_source"] = "CAM"
                solved["constellation"] = sf_utils.radec_to_constellation(
                    solved["RA"], solved["Dec"]
                )
                # see if we can calc alt-az
                solved["Alt"] = None
                solved["Az"] = None
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
                last_image_solve = copy.copy(solved)
                if debug_solve:
                    debug_index += 1
                    tmp_prefix = f"{debug_prefix}{debug_index :0>4}"
                    write_debug(
                        tmp_prefix,
                        console_queue,
                        solve_image,
                        debug_solve,
                        solved,
                        location,
                        imu,
                        dt,
                    )
                    debug_solve = None

            last_solve_time = last_image_time
        else:
            # No new image, check IMU
            # if we don't have an alt/az solve
            # we can't use the IMU
            if solved["Alt"]:
                imu = shared_state.imu()
                if imu:
                    if imu["moving"] or imu_moving == True:
                        # we track imu_moving so that we do
                        # this one more time after we stop moving
                        imu_moving = imu["moving"]
                        location = shared_state.location()
                        dt = shared_state.datetime()
                        if last_image_solve and last_image_solve["Alt"]:
                            # If we have alt, then we have
                            # a position/time

                            # calc new alt/az
                            lis_imu = last_image_solve["imu_pos"]
                            imu_pos = imu["pos"]
                            if lis_imu != None and imu_pos != None:
                                alt_offset = imu_pos[IMU_ALT] - lis_imu[IMU_ALT]
                                alt_offset = (alt_offset + 180) % 360 - 180
                                alt_upd = (last_image_solve["Alt"] - alt_offset) % 360

                                az_offset = imu_pos[IMU_AZ] - lis_imu[IMU_AZ]
                                az_offset = (az_offset + 180) % 360 - 180
                                az_upd = (last_image_solve["Az"] + az_offset) % 360

                                solved["Alt"] = alt_upd
                                solved["Az"] = az_upd

                                # Turn this into RA/DEC
                                solved["RA"], solved["Dec"] = sf_utils.altaz_to_radec(
                                    solved["Alt"], solved["Az"], dt
                                )

                                solved["solve_time"] = time.time()
                                solved["solve_source"] = "IMU"
                                solved[
                                    "constellation"
                                ] = sf_utils.radec_to_constellation(
                                    solved["RA"], solved["Dec"]
                                )
                                shared_state.set_solution(solved)
                                shared_state.set_solve_state(True)
                                last_solve_time = time.time()
