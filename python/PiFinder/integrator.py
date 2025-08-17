#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the solver
* Checks IMU
* Plate solves high-res image

"""

import datetime
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
from PiFinder.pointing_model.astro_coords import RaDecRoll, get_initialized_solved_dict
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
import PiFinder.pointing_model.quaternion_transforms as qt


logger = logging.getLogger("IMU.Integrator")

# Constants:
IMU_MOVED_ANG_THRESHOLD = np.deg2rad(0.1)  # Use IMU tracking if the angle moved is above this 


def integrator(shared_state, solver_queue, console_queue, log_queue, is_debug=True):  # TODO: Change back is_debug=False
    MultiprocLogging.configurer(log_queue)
    """ """
    if is_debug:
        logger.setLevel(logging.DEBUG)
    logger.debug("Starting Integrator")

    try:
        solved = get_initialized_solved_dict()  # Dict of RA, Dec, etc. initialized to None.
        cfg = config.Config()
        
        # Set up dead-reckoning tracking by the IMU:
        imu_dead_reckoning = ImuDeadReckoning(cfg.get_option("screen_direction"))
        #imu_dead_reckoning.set_alignment(q_scope2cam)  # TODO: Enable when q_scope2cam is available

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
                # We have a new image solve: Use plate-solving for RA/Dec
                solved = next_image_solve
                update_plate_solve_and_imu(imu_dead_reckoning, solved)

                last_image_solve = copy.deepcopy(solved)
                solved["solve_source"] = "CAM"

            elif imu_dead_reckoning.tracking:
                # Previous plate-solve exists so use IMU dead-reckoning from
                # the last plate solved coordinates.
                imu = shared_state.imu()
                if imu:
                    update_imu(solved, last_image_solve, imu, imu_dead_reckoning)

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


# ======== Wrapper and helper functions ===============================

def estimate_roll_offset(solved: dict, dt: datetime.datetime) -> float:
    """
    Estimate the roll offset due to misalignment of the camera sensor with
    the mount/scope's coordinate system. The offset is calculated at the
    center of the camera's FoV.

    To calculate the roll with offset: roll = calculated_roll + roll_offset

    TODO: This is currently not being used!
    """
    # Calculate the expected roll at the camera center given the RA/Dec of
    # of the camera center.
    roll_camera_calculated = calc_utils.sf_utils.radec_to_roll(
        solved["camera_center"]["RA"], solved["camera_center"]["Dec"], dt
    )
    roll_offset = solved["camera_center"]["Roll"] - roll_camera_calculated

    return roll_offset


def update_plate_solve_and_imu(imu_dead_reckoning: ImuDeadReckoning, solved: dict):
    """
    Wrapper for ImuDeadReckoning.update_plate_solve_and_imu() to
    interface angles in degrees to radians.

    This updates the pointing model with the plate-solved coordinates and the
    IMU measurements which are assumed to have been taken at the same time.
    """
    if (solved["RA"] is None) or (solved["Dec"] is None):
        return  # No update
    else: 
        # Successfully plate solved & camera pointing exists
        if solved["imu_quat"] is None:
            q_x2imu = np.quaternion(np.nan)
        else:
            q_x2imu = solved["imu_quat"]  # IMU measurement at the time of plate solving
        
        # Convert to radians:
        solved_cam_ra = np.deg2rad(solved["camera_center"]["RA"]) 
        solved_cam_dec = np.deg2rad(solved["camera_center"]["Dec"])
        solved_cam_roll = np.deg2rad(solved["camera_center"]["Roll"])

        # TODO: Target roll isn't calculated by Tetra3. Set to zero here
        solved["Roll"] = 0

        # Update:
        imu_dead_reckoning.update_plate_solve_and_imu(
            solved_cam_ra, solved_cam_dec, solved_cam_roll, q_x2imu)
        
        # Set alignment. TODO: Do this once at alignment. Move out of here.
        set_alignment(imu_dead_reckoning, solved)


def set_alignment(imu_dead_reckoning: ImuDeadReckoning, solved: dict):
    """
    Set alignment. 
    TODO: Do this once at alignment
    """
    # Convert to radians:
    solved_cam_ra = np.deg2rad(solved["camera_center"]["RA"]) 
    solved_cam_dec = np.deg2rad(solved["camera_center"]["Dec"])
    solved_cam_roll = np.deg2rad(solved["camera_center"]["Roll"])
    # Convert to radians:
    target_ra = np.deg2rad(solved["RA"]) 
    target_dec = np.deg2rad(solved["Dec"])
    solved["Roll"] = 0  # TODO: Target roll isn't calculated by Tetra3. Set to zero here
    target_roll = np.deg2rad(solved["Roll"])

    # Calculate q_scope2cam (alignment)
    q_eq2cam = qt.get_q_eq2cam(solved_cam_ra, solved_cam_dec, solved_cam_roll)
    q_eq2scope = qt.get_q_eq2cam(target_ra, target_dec, target_roll)
    q_scope2cam = q_eq2scope.conjugate() * q_eq2cam

    # Set alignment in imu_dead_reckoning
    imu_dead_reckoning.set_alignment(q_scope2cam)


def update_imu(solved: dict, last_image_solve: dict, imu: np.quaternion, imu_dead_reckoning: ImuDeadReckoning):
    """
    Updates the solved dictionary using IMU dead-reckoning from the last
    solved pointing. 
    """
    if not(last_image_solve and imu_dead_reckoning.tracking):
        return  # Need all of these to do IMU dead-reckoning
    
    assert isinstance(imu["quat"] , np.quaternion), "Expecting np.quaternion type"  # TODO: Can be removed later

    # When moving, switch to tracking using the IMU
    angle_moved = qt.get_quat_angular_diff(last_image_solve["imu_quat"], imu["quat"])
    if  angle_moved > IMU_MOVED_ANG_THRESHOLD:
        # Estimate camera pointing using IMU dead-reckoning
        logger.debug("Track using IMU. Angle moved since last_image_solve = "
            "{:}(> threshold = {:})".format(np.rad2deg(angle_moved), 
            np.rad2deg(IMU_MOVED_ANG_THRESHOLD)))
            
        # Dead-reckoning using IMU
        imu_dead_reckoning.update_imu(imu["quat"])  # Latest IMU meas
        
        # Store current camera pointing estimate:
        ra_cam, dec_cam, roll_cam = imu_dead_reckoning.get_cam_radec()
        solved["camera_center"]["RA"] = np.rad2deg(ra_cam)
        solved["camera_center"]["Dec"] = np.rad2deg(dec_cam)
        solved["camera_center"]["Roll"] = np.rad2deg(roll_cam)
        
        # Store the current scope pointing estimate
        ra_target, dec_target, roll_target = imu_dead_reckoning.get_scope_radec()
        solved["RA"] = np.rad2deg(ra_target)
        solved["Dec"] = np.rad2deg(dec_target)
        solved["Roll"] = np.rad2deg(roll_target)  

        q_x2imu = imu["quat"]
        logger.debug("  IMU quat = ({:}, {:}, {:}, {:}".format(q_x2imu.w, q_x2imu.x, q_x2imu.y, q_x2imu.z))

        solved["solve_time"] = time.time()
        solved["solve_source"] = "IMU"
