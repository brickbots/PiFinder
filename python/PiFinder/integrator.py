#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the solver
* Checks IMU
* Plate solves high-res image

TODO:
- Rename solved --> pointing_estimate (also includes IMU)
- Rename next_image_solved --> new_solve
- Rename last_image_solve --> prev_solve (previous successful solve)
- Simplify program flow and explain in comments at top
- Refactor into class PointingTracker

"""
from __future__ import annotations  # To support | in typehints (remove this for Python 3.10+)

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
from PiFinder.types.coordinates import RaDecRoll
from PiFinder.solver import get_initialized_solved_dict
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
import PiFinder.pointing_model.quaternion_transforms as qt


logger = logging.getLogger("IMU.Integrator")

# Constants:
# Use IMU tracking if the angle moved is above this
# TODO: May need to adjust this depending on the IMU sensitivity thresholds
IMU_MOVED_ANG_THRESHOLD = np.deg2rad(0.06)


def integrator(shared_state, solver_queue, console_queue, log_queue, is_debug=False):
    MultiprocLogging.configurer(log_queue)
    """ """
    if is_debug:
        logger.setLevel(logging.DEBUG)
    logger.debug("Starting Integrator")

    try:
        # Dict of RA, Dec, etc. initialized to None:
        solved = get_initialized_solved_dict()
        cfg = config.Config()

        # Set up dead-reckoning tracking by the IMU:
        imu_dead_reckoning = ImuDeadReckoning(cfg.get_option("screen_direction"))

        # This holds the last image solve position info
        # so we can delta for IMU updates
        last_image_solve = None
        last_solve_time = time.time()

        while True:
            pointing_updated = False  # Flag to track if pointing was updated in this loop
            state_utils.sleep_for_framerate(shared_state)

            # Check for new camera solve in queue
            next_image_solve = None
            try:
                next_image_solve = solver_queue.get(block=False)
            except queue.Empty:
                pass

            if type(next_image_solve) is dict:
                # TODO: Refactor this bit:
                # For camera solves, always start from last successful camera solve
                # NOT from shared_state (which may contain IMU drift)
                # This prevents IMU noise accumulation during failed solves
                if last_image_solve:
                    solved = copy.deepcopy(last_image_solve)
                # If no successful solve yet, keep initial solved dict

                # TODO: Create a function to update solve?
                # Update solve metadata (always needed for auto-exposure)
                for key in [
                    "Matches",
                    "RMSE",
                    "last_solve_attempt",
                    "last_solve_success",
                ]:
                    if key in next_image_solve:
                        solved[key] = next_image_solve[key]

                # Only update position data if solve succeeded (RA not None)
                if next_image_solve.get("RA") is not None:
                    solved.update(next_image_solve)

                # For failed solves, preserve ALL position data from previous solve
                # Don't recalculate from GPS (causes drift from GPS noise)

                if solved["RA"] is not None:
                    # Successfully plate-solved:
                    last_image_solve = copy.deepcopy(solved)
                    solved["solve_source"] = "CAM"
                    shared_state.set_solve_state(True)
                    # We have a new image solve: Use plate-solving for RA/Dec
                    update_plate_solve_and_imu(imu_dead_reckoning, solved)
                    pointing_updated = True
                else:
                    # Failed solve - clear constellation
                    solved["solve_source"] = "CAM_FAILED"
                    solved["constellation"] = ""  # NOTE: This gets over-written by IMU dead-reckoning
                    # Push failed solved immediately
                    # This ensures auto-exposure sees Matches=0 for failed solves
                    shared_state.set_solution(solved)
                    shared_state.set_solve_state(False)

            if imu_dead_reckoning.is_initialized() and not pointing_updated:
                # Previous plate-solve exists so use IMU dead-reckoning from
                # the last plate solved coordinates.
                imu = shared_state.imu()
                if imu:
                    update_imu(imu_dead_reckoning, solved, last_image_solve, imu)
                    pointing_updated = True

            # Update Alt, Az only if newer than last push
            if pointing_updated and solved["solve_time"] > last_solve_time:
                solved["constellation"] = get_constellation(solved["RA"], solved["Dec"])

                # TODO: Altaz doesn't seem to be required for catalogs when in 
                # EQ mode? Could be disabled in future when in EQ mode?
                solved["Alt"], solved["Az"] = get_alt_az(solved["RA"], solved["Dec"], 
                                                        shared_state.location(), 
                                                        shared_state.datetime())

                if (solved["RA"] is not None) and (solved["Dec"] is not None):
                    # Push new solved to shared state
                    shared_state.set_solution(solved)
                    shared_state.set_solve_state(True)
                    last_solve_time = solved["solve_time"]

    except EOFError:
        logger.error("Main no longer running for integrator")


# ======== Wrapper and helper functions ===============================

def update_plate_solve_and_imu(imu_dead_reckoning: ImuDeadReckoning, solved: dict):
    """
    Wrapper for ImuDeadReckoning.solve() that converts angles from degrees to
    radians and builds RaDecRoll from the plate-solved camera_solve.
    """
    if (solved["RA"] is None) or (solved["Dec"] is None):
        return  # No update

    if solved["imu_quat"] is None:
        q_x2imu = quaternion.quaternion(np.nan)
    else:
        q_x2imu = solved["imu_quat"]

    pointing = RaDecRoll(
        solved["camera_solve"]["RA"],
        solved["camera_solve"]["Dec"],
        solved["camera_solve"]["Roll"],
        deg=True,
    )
    imu_dead_reckoning.solve(pointing, q_x2imu)


def update_imu(
    imu_dead_reckoning: ImuDeadReckoning,
    solved: dict,
    last_image_solve: dict,
    imu: dict,
):
    """
    Dead-reckon pointing from the latest IMU sample and write it into
    solved["RA"/"Dec"/"Roll"].
    """
    if not (last_image_solve and imu_dead_reckoning.is_initialized()):
        return

    assert isinstance(
        imu["quat"], quaternion.quaternion
    ), "Expecting quaternion.quaternion type"
    q_x2imu = imu["quat"]
    imu_time = time.time()

    angle_moved = qt.get_quat_angular_diff(last_image_solve["imu_quat"], q_x2imu)
    if angle_moved <= IMU_MOVED_ANG_THRESHOLD:
        return

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

    pointing = imu_dead_reckoning.predict(q_x2imu)
    assert pointing is not None  # guaranteed by the is_initialized() check above
    solved["RA"], solved["Dec"], solved["Roll"] = pointing.get(deg=True)
    solved["solve_time"] = imu_time
    solved["solve_source"] = "IMU"

    logger.debug(
        "IMU update: pointing: RA: {:}, Dec: {:}, Roll: {:}".format(
            solved["RA"], solved["Dec"], solved["Roll"]
        )
    )


def get_constellation(RA_deg, Dec_deg) -> str:
    """
    Get constellation name from the current RA/Dec position.
    """
    if RA_deg is None or Dec_deg is None:
        return ""
    else:
        return calc_utils.sf_utils.radec_to_constellation(RA_deg, Dec_deg)


def get_alt_az(RA_deg, Dec_deg, location, dt) -> tuple[float | None, float | None]:
    """
    Get Alt/Az from RA/Dec, location and datetime.
    RETURNS: alt_deg, az_deg
    """
    if RA_deg is None or Dec_deg is None or location is None or dt is None:
        return None, None
    else:
        calc_utils.sf_utils.set_location(location.lat, location.lon, location.altitude)
        return calc_utils.sf_utils.radec_to_altaz(RA_deg, Dec_deg, dt)


