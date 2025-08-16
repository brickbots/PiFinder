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
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoningEqFrame
import PiFinder.pointing_model.quaternion_transforms as qt


logger = logging.getLogger("IMU.Integrator")

# Constants:
IMU_MOVED_ANG_THRESHOLD = np.deg2rad(0.1)  # Use IMU tracking if the angle moved is above this 


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
        # "Alt" and "Az" could be removed once we move to Eq-based dead-reckoning
        solved = {
            "RA": None,  # RA of scope
            "Dec": None,
            "Roll": None,
            "camera_center": {
                "RA": None,
                "Dec": None,
                "Roll": None,
                "Alt": None,  # TODO: Remove Alt, Az keys later?
                "Az": None,
            },
            "camera_solve": {  # camera_solve is NOT updated by IMU dead-reckoning  
                "RA": None,
                "Dec": None,
                "Roll": None,
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
        # TODO: Capture flip_alt_offset by q_imu2camera
        if (
            cfg.get_option("screen_direction") == "left"
            or cfg.get_option("screen_direction") == "flat"
            or cfg.get_option("screen_direction") == "flat3"
            or cfg.get_option("screen_direction") == "straight"
        ):
            flip_alt_offset = True
        else:
            flip_alt_offset = False
        
        # Set up dead-reckoning tracking by the IMU:
        pointing_tracker = ImuDeadReckoningEqFrame(cfg.get_option("screen_direction"))
        #pointing_tracker.set_alignment(q_scope2cam)  # TODO: Enable when q_scope2cam is available

        # This holds the last image solve position info
        # so we can delta for IMU updates
        last_image_solve = None
        last_solve_time = time.time()
        #prev_imu = None  # TODO: For debugging - remove later
        while True:
            state_utils.sleep_for_framerate(shared_state)

            # Check for new camera solve in queue
            next_image_solve = None
            try:
                next_image_solve = solver_queue.get(block=False)
            except queue.Empty:
                pass

            if type(next_image_solve) is dict:
                # We have a new image solve: Use this for RA/Dec
                solved = next_image_solve

                location = shared_state.location()
                dt = shared_state.datetime()

                if location and dt:
                    # We have position and time/date! TODO: Check if this dt is needed
                    update_solve_eq(solved, location, dt, pointing_tracker)

                last_image_solve = copy.deepcopy(solved)
                solved["solve_source"] = "CAM"

            elif pointing_tracker.tracking:
                # Previous plate-solve exists so use IMU dead-reckoning from
                # the last plate solved coordinates.
                imu = shared_state.imu()
                if imu:
                    dt = shared_state.datetime()
                    update_imu_eq(solved, last_image_solve, imu, dt, pointing_tracker)

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


# ======== EQ version ===============================

def update_solve_eq(solved, location, dt, pointing_tracker):
    """
    Updates the solved dic based on the plate-solved coordinates. Uses the
    altaz coordinates and horizontal frame for IMU tracking. Moved from the
    loop inside integrator integrator
    """
    assert location and dt, "Need location and time"
    
    # Commented out Altaz coords which are not needed TODO: Remove these later 
    """
    solved["Alt"] = None
    solved["Az"] = None
    """
    # TODO: May be able to remove this later
    calc_utils.sf_utils.set_location(
        location.lat,
        location.lon,
        location.altitude,
    )
    """
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
    solved["Roll_offset"] = estimate_roll_offset(solved, dt)  # TODO: Remove later?
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
    """

    # Update with plate solved coordinates of camera center & IMU measurement
    update_plate_solve_and_imu_eq__degrees(pointing_tracker, solved)  


def update_plate_solve_and_imu_eq__degrees(pointing_tracker, solved):
    """
    Wrapper for ImuDeadReckoningEqFrame.update_plate_solve_and_imu() to
    interface angles in degrees to radians.

    This updates the pointing model with the plate-solved coordinates and the
    IMU measurements which are assumed to have been taken at the same time.
    """
    if (solved["RA"] is None) or (solved["Dec"] is None):
        return  # No update
    else: 
        # Successfully plate solved & camera pointing exists
        q_x2imu = solved["imu_quat"]  # IMU measurement at the time of plate solving
        
        # Convert to radians:
        solved_cam_ra = np.deg2rad(solved["camera_center"]["RA"]) 
        solved_cam_dec = np.deg2rad(solved["camera_center"]["Dec"])
        solved_cam_roll = np.deg2rad(solved["camera_center"]["Roll"])
        # Convert to radians:
        target_ra = np.deg2rad(solved["RA"]) 
        target_dec = np.deg2rad(solved["Dec"])
        solved["Roll"] = 0  # TODO: Target roll isn't calculated by Tetra3. Set to zero here
        target_roll = np.deg2rad(solved["Roll"])

        # Update:
        pointing_tracker.update_plate_solve_and_imu(
            solved_cam_ra, solved_cam_dec, solved_cam_roll, q_x2imu)

        # Set alignment: TODO: Do this once at alignment
        q_eq2cam = qt.get_q_eq2cam(solved_cam_ra, solved_cam_dec, solved_cam_roll)
        q_eq2scope = qt.get_q_eq2cam(target_ra, target_dec, target_roll)
        q_scope2cam = q_eq2scope.conjugate() * q_eq2cam
        pointing_tracker.set_alignment(q_scope2cam)


def update_imu_eq(solved, last_image_solve, imu, dt, pointing_tracker):
    """
    Updates the solved dictionary using IMU dead-reckoning from the last
    solved pointing. 
    """
    if not(last_image_solve and pointing_tracker.tracking and dt):
        return  # Need all of these to do IMU dead-reckoning

    # TODO: For debugging -- remove later
    #if prev_imu is None or qt.get_quat_angular_diff(prev_imu, imu["quat"]) > 1E-4:
    #    print("Quat: ", imu["quat"])
    #prev_imu = imu["quat"].copy()

    # When moving, switch to tracking using the IMU
    #if imu_moved(lis_imu, imu_pos):
    assert isinstance(imu["quat"] , quaternion.quaternion), "Expecting quaternion.quaternion type"  # TODO: Remove later
    angle_moved = qt.get_quat_angular_diff(last_image_solve["imu_quat"], imu["quat"])
    if  angle_moved > IMU_MOVED_ANG_THRESHOLD:
        # Estimate camera pointing using IMU dead-reckoning
        logger.debug("Track using IMU. Angle moved since last_image_solve = "
            "{:}(> threshold = {:})".format(np.rad2deg(angle_moved), 
            np.rad2deg(IMU_MOVED_ANG_THRESHOLD)))
            
        # Dead-reckoning using IMU
        pointing_tracker.update_imu(imu["quat"])  # Latest IMU meas
        
        # Store current camera pointing estimate:
        ra_cam, dec_cam, roll_cam, dead_reckoning_flag = pointing_tracker.get_cam_radec()
        solved["camera_center"]["RA"] = np.rad2deg(ra_cam)
        solved["camera_center"]["Dec"] = np.rad2deg(dec_cam)
        solved["camera_center"]["Roll"] = np.rad2deg(roll_cam)
        
        # Store the current scope pointing estimate
        ra_target, dec_target, roll_target, dead_reckoning_flag = pointing_tracker.get_scope_radec()
        solved["RA"] = np.rad2deg(ra_target)
        solved["Dec"] = np.rad2deg(dec_target)
        solved["Roll"] = np.rad2deg(roll_target)  

        """
        # TODO: This part for cam2scope will probably be an issue for Altaz mounts 
        # From the alignment. Add this offset to the camera center to get
        # the scope altaz coordinates. TODO: This could be calculated once
        # at alignment? Or when last solved
        cam2scope_offset_az = last_image_solve["Az"] - last_image_solve["camera_center"]["Az"]
        cam2scope_offset_alt = last_image_solve["Alt"] - last_image_solve["camera_center"]["Alt"]
        # Transform to scope center TODO: need to define q_cam2scope
        solved["Az"] = solved["camera_center"]["Az"] + cam2scope_offset_az
        solved["Alt"] = solved["camera_center"]["Alt"] + cam2scope_offset_alt
        """

        q_x2imu = imu["quat"]
        logger.debug("  IMU quat = ({:}, {:}, {:}, {:}".format(q_x2imu.w, q_x2imu.x, q_x2imu.y, q_x2imu.z))

        solved["solve_time"] = time.time()
        solved["solve_source"] = "IMU"
