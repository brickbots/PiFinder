"""
Pointing math: IMU dead-reckoning updates, plate-solve integration,
roll/constellation/altaz finalization.

Pure functions operating on solved dicts and ImuDeadReckoning — no process
state, no queues.  Shared by integrator.py and telemetry.py.
"""

import datetime
import logging
import time

import numpy as np
import quaternion  # numpy-quaternion

import PiFinder.calc_utils as calc_utils
from PiFinder.pointing_model.astro_coords import RaDecRoll
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
import PiFinder.pointing_model.quaternion_transforms as qt

logger = logging.getLogger("IMU.Integrator")

# Use IMU tracking if the angle moved is above this
IMU_MOVED_ANG_THRESHOLD = np.deg2rad(0.06)


def finalize_and_push_solution(shared_state, solved, mount_type):
    """Compute roll, constellation, altaz and push solution to shared_state."""
    location = shared_state.location()
    dt = shared_state.datetime()
    if location:
        calc_utils.sf_utils.set_location(location.lat, location.lon, location.altitude)

    solved["Roll"] = get_roll_by_mount_type(
        solved["RA"], solved["Dec"], location, dt, mount_type
    )
    solved["constellation"] = calc_utils.sf_utils.radec_to_constellation(
        solved["RA"], solved["Dec"]
    )
    if location and dt:
        solved["Alt"], solved["Az"] = calc_utils.sf_utils.radec_to_altaz(
            solved["RA"], solved["Dec"], dt
        )

    shared_state.set_solution(solved)
    shared_state.set_solve_state(True)


def update_plate_solve_and_imu(imu_dead_reckoning: ImuDeadReckoning, solved: dict):
    """
    Wrapper for ImuDeadReckoning.update_plate_solve_and_imu() to
    interface angles in degrees to radians.

    This updates the pointing model with the plate-solved coordinates and the
    IMU measurements which are assumed to have been taken at the same time.
    """
    if solved["RA"] is None or solved["Dec"] is None:
        return

    if solved["imu_quat"] is None:
        q_x2imu = quaternion.quaternion(np.nan)
    else:
        q_x2imu = solved["imu_quat"]

    solved_cam = RaDecRoll()
    solved_cam.set_from_deg(
        solved["camera_center"]["RA"],
        solved["camera_center"]["Dec"],
        solved["camera_center"]["Roll"],
    )
    imu_dead_reckoning.update_plate_solve_and_imu(solved_cam, q_x2imu)

    set_cam2scope_alignment(imu_dead_reckoning, solved)


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
        return

    assert isinstance(
        imu["quat"], quaternion.quaternion
    ), "Expecting quaternion.quaternion type"
    q_x2imu = imu["quat"]

    angle_moved = qt.get_quat_angular_diff(last_image_solve["imu_quat"], q_x2imu)
    if angle_moved > IMU_MOVED_ANG_THRESHOLD:
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

        imu_dead_reckoning.update_imu(q_x2imu)

        cam_eq = imu_dead_reckoning.get_cam_radec()
        (
            solved["camera_center"]["RA"],
            solved["camera_center"]["Dec"],
            solved["camera_center"]["Roll"],
        ) = cam_eq.get_deg(use_none=True)

        scope_eq = imu_dead_reckoning.get_scope_radec()
        solved["RA"], solved["Dec"], solved["Roll"] = scope_eq.get_deg(use_none=True)

        solved["solve_time"] = time.time()
        solved["solve_source"] = "IMU"

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


def set_cam2scope_alignment(imu_dead_reckoning: ImuDeadReckoning, solved: dict):
    """Set the camera-to-scope alignment in the dead-reckoning model."""
    solved_cam = RaDecRoll()
    solved_cam.set_from_deg(
        solved["camera_center"]["RA"],
        solved["camera_center"]["Dec"],
        solved["camera_center"]["Roll"],
    )

    solved["Roll"] = 0  # Target roll isn't calculated by Tetra3
    solved_scope = RaDecRoll()
    solved_scope.set_from_deg(solved["RA"], solved["Dec"], solved["Roll"])

    imu_dead_reckoning.set_cam2scope_alignment(solved_cam, solved_scope)


def get_roll_by_mount_type(
    ra_deg: float,
    dec_deg: float,
    location,
    dt: datetime.datetime,
    mount_type: str,
) -> float:
    """
    Returns the roll (in degrees) depending on the mount type so that the chart
    is displayed appropriately for the mount type.

    * Alt/Az mount: Display the chart in the horizontal coordinate so that up
      in the chart points to the Zenith.
    * EQ mount: Display the chart in the equatorial coordinate system with the
      NCP up so roll = 0.

    Assumes that location has already been set in calc_utils.sf_utils.
    """
    if mount_type == "Alt/Az":
        if location and dt:
            roll_deg = calc_utils.sf_utils.radec_to_roll(ra_deg, dec_deg, dt)

            # HACK: The IMU direction flips at a certain point. Could be due to
            # an issue in calc_utils.sf_utils.hadec_to_roll().
            ha_deg = calc_utils.sf_utils.ra_to_ha(ra_deg, dt)
            roll_deg = roll_deg - np.sign(ha_deg) * 180
        else:
            roll_deg = 0.0
    elif mount_type == "EQ":
        roll_deg = 0.0
    else:
        logger.error(f"Unknown mount type: {mount_type}. Cannot set roll.")
        roll_deg = 0.0

    # Adjust roll for hemisphere
    if location and location.lat < 0.0:
        roll_deg += 180.0

    return roll_deg
