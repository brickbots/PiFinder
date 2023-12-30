#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the solver
* Checks IMU
* Plate solves high-res image

"""
import queue
import time
import copy
import logging

from PiFinder import config
import PiFinder.calc_utils as calc_utils

IMU_ALT = 2
IMU_AZ = 0


def imu_moved(imu_a, imu_b):
    """
    Compares two IMU states to determine if they are the 'same'
    if either is none, returns False
    """
    if imu_a == None:
        return False
    if imu_b == None:
        return False

    # figure out the abs difference
    diff = (
        abs(imu_a[0] - imu_b[0]) + abs(imu_a[1] - imu_b[1]) + abs(imu_a[2] - imu_b[2])
    )
    if diff > 0.001:
        return True
    return False


def integrator(shared_state, solver_queue, console_queue):
    try:
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
        }
        cfg = config.Config()
        if (
            cfg.get_option("screen_direction") == "left"
            or cfg.get_option("screen_direction") == "flat"
        ):
            flip_alt_offset = True
        else:
            flip_alt_offset = False

        # This holds the last image solve position info
        # so we can delta for IMU updates
        last_image_solve = None
        last_solved = None
        last_solve_time = time.time()
        while True:
            if shared_state.power_state() <= 0:
                time.sleep(0.5)
            else:
                time.sleep(1 / 30)

            # Check for new camera solve in queue
            next_image_solve = None
            try:
                next_image_solve = solver_queue.get(block=False)
                logging.debug("Next image solve is %s", next_image_solve)
            except queue.Empty:
                pass

            if next_image_solve:
                solved = next_image_solve

                # see if we can generate alt/az
                location = shared_state.location()
                dt = shared_state.datetime()

                # see if we can calc alt-az
                solved["Alt"] = None
                solved["Az"] = None
                if location and dt:
                    # We have position and time/date!
                    calc_utils.sf_utils.set_location(
                        location["lat"],
                        location["lon"],
                        location["altitude"],
                    )
                    alt, az = calc_utils.sf_utils.radec_to_altaz(
                        solved["RA"],
                        solved["Dec"],
                        dt,
                    )
                    solved["Alt"] = alt
                    solved["Az"] = az

                last_image_solve = copy.copy(solved)
                solved["solve_source"] = "CAM"

            # generate new solution by offsetting last camera solve
            # if we don't have an alt/az solve
            # we can't use the IMU
            elif solved["Alt"]:
                imu = shared_state.imu()
                if imu:
                    dt = shared_state.datetime()
                    if last_image_solve and last_image_solve["Alt"]:
                        # If we have alt, then we have
                        # a position/time

                        # calc new alt/az
                        lis_imu = last_image_solve["imu_pos"]
                        imu_pos = imu["pos"]
                        if imu_moved(lis_imu, imu_pos):
                            alt_offset = imu_pos[IMU_ALT] - lis_imu[IMU_ALT]
                            if flip_alt_offset:
                                alt_offset = ((alt_offset + 180) % 360 - 180) * -1
                            else:
                                alt_offset = (alt_offset + 180) % 360 - 180
                            alt_upd = (last_image_solve["Alt"] - alt_offset) % 360

                            az_offset = imu_pos[IMU_AZ] - lis_imu[IMU_AZ]
                            az_offset = (az_offset + 180) % 360 - 180
                            az_upd = (last_image_solve["Az"] + az_offset) % 360

                            solved["Alt"] = alt_upd
                            solved["Az"] = az_upd

                            # Turn this into RA/DEC
                            (
                                solved["RA"],
                                solved["Dec"],
                            ) = calc_utils.sf_utils.altaz_to_radec(
                                solved["Alt"], solved["Az"], dt
                            )

                            solved["solve_time"] = time.time()
                            solved["solve_source"] = "IMU"

            # Is the solution new?
            if solved["RA"] and solved["solve_time"] > last_solve_time:
                last_solve_time = time.time()
                # Update remaining solved keys
                solved["constellation"] = calc_utils.sf_utils.radec_to_constellation(
                    solved["RA"], solved["Dec"]
                )

                # add solution
                shared_state.set_solution(solved)
                shared_state.set_solve_state(True)
                last_solved = solved
    except EOFError:
        logging.error("Main no longer running for integrator")
