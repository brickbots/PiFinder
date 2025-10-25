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
from PiFinder.pointing_model.astro_coords import initialized_solved_dict, RaDecRoll
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
import PiFinder.pointing_model.quaternion_transforms as qt


logger = logging.getLogger("IMU.Integrator")

# Constants:
# Use IMU tracking if the angle moved is above this
IMU_MOVED_ANG_THRESHOLD = np.deg2rad(0.1)


def integrator(shared_state, solver_queue, console_queue, log_queue, is_debug=False):
    MultiprocLogging.configurer(log_queue)
    """ """
    if is_debug:
        logger.setLevel(logging.DEBUG)
    logger.debug("Starting Integrator")

    try:
        # Dict of RA, Dec, etc. initialized to None:
        solved = initialized_solved_dict()
        cfg = config.Config()

        mount_type = cfg.get_option("mount_type")
        logger.debug(f"mount_type = {mount_type}")

        # Set up dead-reckoning tracking by the IMU:
        imu_dead_reckoning = ImuDeadReckoning(cfg.get_option("screen_direction"))
        # imu_dead_reckoning.set_alignment(q_scope2cam)  # TODO: Enable when q_scope2cam is available from alignment

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
                    update_imu(imu_dead_reckoning, solved, last_image_solve, imu)

            # Is the solution new?
            if solved["RA"] and solved["solve_time"] > last_solve_time:
                last_solve_time = time.time()

                # Try to set date and time
                location = shared_state.location()
                dt = shared_state.datetime()
                # Set location for roll and altaz calculations.
                # TODO: Is itnecessary to set location?
                # TODO: Altaz doesn't seem to be required for catalogs when in
                # EQ mode? Could be disabled in future when in EQ mode?
                calc_utils.sf_utils.set_location(
                    location.lat, location.lon, location.altitude
                )

                # Set the roll so that the chart is displayed appropriately for the mount type
                solved["Roll"] = get_roll_by_mount_type(
                    solved["RA"], solved["Dec"], location, dt, mount_type
                )

                # Update remaining solved keys
                solved["constellation"] = calc_utils.sf_utils.radec_to_constellation(
                    solved["RA"], solved["Dec"]
                )

                # Set Alt/Az because it's needed for the catalogs for the
                # Alt/Az mount type. TODO: Can this be moved to the catalog?
                dt = shared_state.datetime()
                if location and dt:
                    solved["Alt"], solved["Az"] = calc_utils.sf_utils.radec_to_altaz(
                        solved["RA"], solved["Dec"], dt
                    )

                # add solution
                shared_state.set_solution(solved)
                shared_state.set_solve_state(True)

    except EOFError:
        logger.error("Main no longer running for integrator")


# ======== Wrapper and helper functions ===============================


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
            q_x2imu = quaternion.quaternion(np.nan)
        else:
            q_x2imu = solved["imu_quat"]  # IMU measurement at the time of plate solving

        # Update:
        solved_cam = RaDecRoll()
        solved_cam.set_from_deg(
            solved["camera_center"]["RA"],
            solved["camera_center"]["Dec"],
            solved["camera_center"]["Roll"],
        )
        imu_dead_reckoning.update_plate_solve_and_imu(solved_cam, q_x2imu)

        # Set alignment. TODO: Do this once at alignment. Move out of here.
        set_alignment(imu_dead_reckoning, solved)


def set_alignment(imu_dead_reckoning: ImuDeadReckoning, solved: dict):
    """
    Set alignment.
    TODO: Do this once at alignment
    """
    # RA, Dec of camera center::
    solved_cam = RaDecRoll()
    solved_cam.set_from_deg(
        solved["camera_center"]["RA"],
        solved["camera_center"]["Dec"],
        solved["camera_center"]["Roll"],
    )

    # RA, Dec of target (where scope is pointing):
    solved["Roll"] = 0  # Target roll isn't calculated by Tetra3. Set to zero here
    solved_scope = RaDecRoll()
    solved_scope.set_from_deg(solved["RA"], solved["Dec"], solved["Roll"])

    # Set alignment in imu_dead_reckoning
    imu_dead_reckoning.set_alignment(solved_cam, solved_scope)


def update_imu(
    imu_dead_reckoning: ImuDeadReckoning,
    solved: dict,
    last_image_solve: dict,
    imu: dict,
):
    """
    Updates the solved dictionary using IMU dead-reckoning from the last
    solved pointing.
    """
    if not (last_image_solve and imu_dead_reckoning.tracking):
        return  # Need all of these to do IMU dead-reckoning

    assert isinstance(
        imu["quat"], quaternion.quaternion
    ), "Expecting quaternion.quaternion type"  # TODO: Can be removed later
    q_x2imu = imu["quat"]  # Current IMU measurement (quaternion)

    # When moving, switch to tracking using the IMU
    angle_moved = qt.get_quat_angular_diff(last_image_solve["imu_quat"], q_x2imu)
    if angle_moved > IMU_MOVED_ANG_THRESHOLD:
        # Estimate camera pointing using IMU dead-reckoning
        logger.debug(
            "Track using IMU: Angle moved since last_image_solve = "
            "{:}(> threshold = {:}) | IMU quat = ({:}, {:}, {:}, {:})".format(
                np.rad2deg(angle_moved),
                np.rad2deg(IMU_MOVED_ANG_THRESHOLD),
                q_x2imu.w,
                q_x2imu.x,
                q_x2imu.y,
                q_x2imu.z,
            )
        )

        # Dead-reckoning using IMU
        imu_dead_reckoning.update_imu(q_x2imu)  # Latest IMU measurement

        # Store current camera pointing estimate:
        cam_eq = imu_dead_reckoning.get_cam_radec()
        (
            solved["camera_center"]["RA"],
            solved["camera_center"]["Dec"],
            solved["camera_center"]["Roll"],
        ) = cam_eq.get_deg(use_none=True)

        # Store the current scope pointing estimate
        scope_eq = imu_dead_reckoning.get_scope_radec()
        solved["RA"], solved["Dec"], solved["Roll"] = scope_eq.get_deg(use_none=True)

        solved["solve_time"] = time.time()
        solved["solve_source"] = "IMU"

        # Logging for states updated in solved:
        logger.debug(
            "IMU update: scope: RA: {:}, Dec: {:}, Roll: {:}".format(
                solved["RA"], solved["Dec"], solved["Roll"]
            )
        )
        logger.debug(
            "IMU update: camera_center: RA: {:}, Dec: {:}, Roll: {:}".format(
                solved["camera_center"]["RA"],
                solved["camera_center"]["Dec"],
                solved["camera_center"]["Roll"],
            )
        )


def get_roll_by_mount_type(
    ra_deg: float, dec_deg: float, location, dt: datetime.datetime, mount_type: str
) -> float:
    """
    Returns the roll (in degrees) depending on the mount type so that the chart
    is displayed appropriately for the mount type. The RA and Dec of the target
    should be provided (in degrees).

    * Alt/Az mount: Display the chart in the horizontal coordinate so the
    * EQ mount: Display the chart in the equatorial coordinate system with the
      NCP up so roll = 0.

    Assumes that location has already been set in calc_utils.sf_utils.
    """
    if mount_type == "Alt/Az":
        # Altaz mounts: Display chart in horizontal coordinates
        if location and dt:
            # We have location and time/date (and assume that location has been set)
            # Roll at the target RA/Dec in the horizontal frame
            roll_deg = calc_utils.sf_utils.radec_to_roll(ra_deg, dec_deg, dt)
        else:
            # No position or time/date available, so set roll to 0
            roll_deg = 0

    elif mount_type == "EQ":
        # EQ-mounts: Display chart with NCP up so roll = 0
        roll_deg = 0
    else:
        logger.error(f"Unknown mount type: {mount_type}. Cannot set roll.")
        roll_deg = 0

    return roll_deg
