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
import numpy as np
import quaternion  # numpy-quaternion

from PiFinder import config
from PiFinder import state_utils
import PiFinder.calc_utils as calc_utils
from PiFinder.multiproclogging import MultiprocLogging
import PiFinder.pointing_model.pointing_model as pointing

IMU_ALT = 2
IMU_AZ = 0

logger = logging.getLogger("IMU.Integrator")


# TODO: Remove this after migrating to quaternion
def imu_moved(imu_a, imu_b):
    """
    Compares two IMU states to determine if they are the 'same'
    if either is none, returns False
    
    **TODO: This imu_a and imu_b used to be pos. They are now quaternions**
    """
    if imu_a is None:
        return False
    if imu_b is None:
        return False

    # figure out the abs difference
    diff = (
        abs(imu_a[0] - imu_b[0]) + abs(imu_a[1] - imu_b[1]) + abs(imu_a[2] - imu_b[2])
    )
    if diff > 0.001:
        return True
    return False


def integrator(shared_state, solver_queue, console_queue, log_queue, is_debug=True):  # TODO: Change back is_debug=False
    MultiprocLogging.configurer(log_queue)
    try:
        if is_debug:
            logger.setLevel(logging.DEBUG)
        logger.debug("Starting Integrator")

        # TODO: This dict is duplicated in solver.py - Refactor?
        solved = {
            "RA": None,  # RA of scope
            "Dec": None,
            "Roll": None,
            "camera_center": {
                "RA": None,
                "Dec": None,
                "Roll": None,
                "Alt": None,
                "Az": None,
            },
            "camera_solve": {  # camera_solve is NOT updated by IMU dead-reckoning  
                "RA": None,
                "Dec": None,
                "Roll": None,
            },
            "imu": {
                "q_hor2x": None,
            },
            "Roll_offset": 0,  # May/may not be needed - for experimentation
            "imu_pos": None,
            "imu_quat": None,  # IMU quaternion as numpy quaternion (scalar-first) - TODO: Move to "imu"
            "Alt": None,  # Alt of scope
            "Az": None,
            "solve_source": None,
            "solve_time": None,
            "cam_solve_time": 0,
            "constellation": None,
        }
        cfg = config.Config()
        #"""  Disable dependence of IMU on PiFinder type
        if (
            cfg.get_option("screen_direction") == "left"
            or cfg.get_option("screen_direction") == "flat"
            or cfg.get_option("screen_direction") == "flat3"
            or cfg.get_option("screen_direction") == "straight"
        ):
            flip_alt_offset = True
        else:
            flip_alt_offset = False
        #"""

        imu_moved_ang_threshold = np.deg2rad(0.1)  # Use IMU tracking if the angle moved is above this 
            
        # This holds the last image solve position info
        # so we can delta for IMU updates
        last_image_solve = None
        last_solve_time = time.time()
        while True:
            state_utils.sleep_for_framerate(shared_state)

            # Check for new camera solve in queue
            next_image_solve = None
            try:
                next_image_solve = solver_queue.get(block=False)
            except queue.Empty:
                pass

            if type(next_image_solve) is dict:
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
                        location.lat,
                        location.lon,
                        location.altitude,
                    )
                    alt, az = calc_utils.sf_utils.radec_to_altaz(
                        solved["RA"],
                        solved["Dec"],
                        dt,
                    )
                    solved["Alt"] = alt
                    solved["Az"] = az

                    alt, az = calc_utils.sf_utils.radec_to_altaz(
                        solved["camera_center"]["RA"],
                        solved["camera_center"]["Dec"],
                        dt,
                    )
                    solved["camera_center"]["Alt"] = alt
                    solved["camera_center"]["Az"] = az

                    # Experimental: For monitoring roll offset
                    # Estimate the roll offset due misalignment of the
                    # camera sensor with the Pole-to-Source great circle.
                    solved["Roll_offset"] = estimate_roll_offset(solved, dt)
                    # Find the roll at the target RA/Dec. Note that this doesn't include the
                    # roll offset so it's not the roll that the PiFinder cameara sees but the
                    # roll relative to the celestial pole given the RA and Dec.
                    roll_target_calculated = calc_utils.sf_utils.radec_to_roll(
                        solved["RA"], solved["Dec"], dt
                    )
                    # Compensate for the roll offset. This gives the roll at the target
                    # as seen by the camera.
                    solved["Roll"] = roll_target_calculated + solved["Roll_offset"]

                    # calculate roll for camera center
                    roll_target_calculated = calc_utils.sf_utils.radec_to_roll(
                        solved["camera_center"]["RA"],
                        solved["camera_center"]["Dec"],
                        dt,
                    )
                    # Compensate for the roll offset. This gives the roll at the target
                    # as seen by the camera.
                    solved["camera_center"]["Roll"] = (
                        roll_target_calculated + solved["Roll_offset"]
                    )

                    # Use plate-solved pointing and IMU measurement to set up 
                    # IMU dead reckoning:
                    solved["imu"]["q_hor2x"] = get_imu_reference_frame(solved, shared_state)
                    # From the alignment. Add this offset to the camera center to get
                    # the scope altaz coordinates. TODO: This could be calculated once
                    # at alignment?
                    cam2scope_offset_az = solved["Az"] - solved["camera_center"]["Az"]
                    cam2scope_offset_alt = solved["Alt"] - solved["camera_center"]["Alt"]
                    # TODO: Do something similar for EQ mounts here
                    logger.debug("Coordinates stored from plate solve.")

                last_image_solve = copy.deepcopy(solved)
                solved["solve_source"] = "CAM"

            # Use IMU dead-reckoning from the last camera solve:
            # 1) Check we have an alt/az solve, otherwise we can't use the IMU
            # If Alt exists:
            # 2) Calculate the difference in the IMU measurements since the
            # last plage solve. IMU "pos" is stored as Alt/Az.
            # 3) Add the relative Alt/Az difference from the IMU to the plate
            # -solved Alt/Az to give a dead-reckoning estimate of the current
            # position.
            elif solved["Alt"]:
                imu = shared_state.imu()
                if imu:
                    dt = shared_state.datetime()
                    if last_image_solve and last_image_solve["Alt"] and last_image_solve["imu"]["q_hor2x"]:
                        # If we have alt, then we have a position/time

                        # calc new alt/az
                        # When moving, switch to tracking using the IMU
                        #if imu_moved(lis_imu, imu_pos):
                        assert isinstance(imu["quat"] , quaternion.quaternion), "Expecting quaternion.quaternion type"  # TODO: Remove later
                        angle_moved = pointing.get_quat_angular_diff(last_image_solve["imu_quat"], imu["quat"])
                        logger.debug("Track using IMU. Angle moved = {:}".format(np.rad2deg(angle_moved)))
                        if  angle_moved > imu_moved_ang_threshold:
                            # Estimate camera pointing using IMU dead-reckoning
                            q_x2imu = imu["quat"]  # Latest IMU meas: quaternion rot. of IMU rel. to some frame X 
                            q_hor2x = last_image_solve["imu"]["q_hor2x"]
                            q_imu2cam = np.quaternion(1, 0, 0, 0)  # Identity so this could be removed later (TODO)
                            q_hor2cam = q_hor2x * q_x2imu * q_imu2cam
                            q_hor2cam = q_hor2cam.normalized()
                            # Store estimate:
                            az_rad, alt_rad = pointing.get_altaz_from_q_hor2scope(q_hor2cam)
                            solved["camera_center"]["Az"] = np.rad2deg(az_rad)
                            solved["camera_center"]["Alt"] = np.rad2deg(alt_rad)

                            # Transform to scope center
                            solved["Az"] = solved["camera_center"]["Az"] + cam2scope_offset_az
                            solved["Alt"] = solved["camera_center"]["Alt"] + cam2scope_offset_alt

                            # TODO: need to define q_cam2scope
                            #q_hor2scope = q_hor2cam * q_cam2scope
                      

                            """ DISABLE - Use quaternions
                            # calc new alt/az - OLD method
                            lis_imu = last_image_solve["imu_pos"]
                            imu_pos = imu["pos"]
                            alt_offset = imu_pos[IMU_ALT] - lis_imu[IMU_ALT]
                            if flip_alt_offset:
                                alt_offset = ((alt_offset + 180) % 360 - 180) * -1
                            else:
                                alt_offset = (alt_offset + 180) % 360 - 180
                            solved["Alt"] = (last_image_solve["Alt"] - alt_offset) % 360
                            solved["camera_center"]["Alt"] = (
                                last_image_solve["camera_center"]["Alt"] - alt_offset
                            ) % 360

                            az_offset = imu_pos[IMU_AZ] - lis_imu[IMU_AZ]
                            az_offset = (az_offset + 180) % 360 - 180
                            solved["Az"] = (last_image_solve["Az"] + az_offset) % 360
                            solved["camera_center"]["Az"] = (
                                last_image_solve["camera_center"]["Az"] + az_offset
                            ) % 360
                            """

                            # N.B. Assumes that location hasn't changed since last solve
                            # Turn this into RA/DEC
                            (
                                solved["RA"],
                                solved["Dec"],
                            ) = calc_utils.sf_utils.altaz_to_radec(
                                solved["Alt"], solved["Az"], dt
                            )
                            # Calculate the roll at the target RA/Dec and compensate for the offset.
                            solved["Roll"] = (
                                calc_utils.sf_utils.radec_to_roll(
                                    solved["RA"], solved["Dec"], dt
                                )
                                + solved["Roll_offset"]
                            )

                            # Now for camera centered solve
                            (
                                solved["camera_center"]["RA"],
                                solved["camera_center"]["Dec"],
                            ) = calc_utils.sf_utils.altaz_to_radec(
                                solved["camera_center"]["Alt"],
                                solved["camera_center"]["Az"],
                                dt,
                            )
                            # Calculate the roll at the target RA/Dec and compensate for the offset.
                            solved["camera_center"]["Roll"] = (
                                calc_utils.sf_utils.radec_to_roll(
                                    solved["camera_center"]["RA"],
                                    solved["camera_center"]["Dec"],
                                    dt,
                                )
                                + solved["Roll_offset"]
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
    except EOFError:
        logger.error("Main no longer running for integrator")


def estimate_roll_offset(solved, dt):
    """
    Estimate the roll offset due to misalignment of the camera sensor with
    the mount/scope's coordinate system. The offset is calculated at the
    center of the camera's FoV.

    To calculate the roll with offset: roll = calculated_roll + roll_offset
    """
    # Calculate the expected roll at the camera center given the RA/Dec of
    # of the camera center.
    roll_camera_calculated = calc_utils.sf_utils.radec_to_roll(
        solved["camera_center"]["RA"], solved["camera_center"]["Dec"], dt
    )
    roll_offset = solved["camera_center"]["Roll"] - roll_camera_calculated

    return roll_offset


def get_imu_reference_frame(solved, shared_state):
    """
    The IMU quaternion measurements, q_x2imu, are relative to some arbitrary
    drifting frame X. This uses the latest plate solved coordinate with the
    latest IMU measurement to solve for the IMU's reference frame X. The frame
    X is expressed by the quaternion rotation q_hor2x from the Horizontal frame
    to X. Once we know q_hor2x, we can infer the camera pointing using the IMU
    data by dead reckoning: q_hor2cam = q_hor2x * q_x2imu * q_imu2cam

    This assumes that plate solving was successful and camera coordinates are
    available. It also assumes that the IMU measurement is available. If these
    conditions are not met, this function will return None. We also assume that
    the plate solve and IMU measurements availalbe are simultaneous. Note that
    q_hor2x will drift over time.

    INPUT: 
    solved: Dictionary of the latest plate-solved data

    RETURNS: 
    q_hor2x: [numpy.quaternion] Quaternion of the IMU's drifting reference 
             frame X relative to the Horizontal frame. Returns None if the
             plate-solved pointing or IMU data aren't available.
    """
    q_hor2x = None

    if solved["Alt"]:
        # Successfully plate solved & camera pointing exists
        #imu = shared_state.imu() # TODO: Usage above. Remove? Also remove shared_state as input?
        imu_meas = solved["imu_quat"]  # Should be the IMU measurement at the time of plate solving
        if imu_meas:
            # We have both the plate solved camera pointing and an IMU 
            # measurement (we'll assume that they are at the same timestamp).

            # Get plate-solved pointing from the camera as quaternion:
            # Assumes that the PiFinder camera is on a perfect altaz mount
            q_hor2cam = pointing.get_q_hor2scope(
                np.deg2rad(solved["camera_center"]["Az"]), 
                np.deg2rad(solved["camera_center"]["Alt"]))

            # Get latest IMU data: quaternion rot. of IMU rel. to some drifting 
            # reference frame X that the IMU uses as its reference
            q_x2imu = imu_meas # Rename to make the transformation expilicit
            q_x2imu = q_x2imu.normalized()

            # Solve for the arbitrary drifting reference frame X using the 
            # camera pointing. This will be used during dead reckoning with 
            # the IMU until the next plate solve.
            q_cam2imu = np.quaternion(1, 0, 0, 0)  # Identity so this could be removed later (TODO)
            q_hor2x = q_hor2cam * q_cam2imu * q_x2imu.conj()
            q_hor2x = q_hor2x.normalized()

    return q_hor2x
