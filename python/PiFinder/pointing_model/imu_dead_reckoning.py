"""
IMU dead-reckoning extrapolates the scope pointing from the last plate-solved
coordinate using the IMU measurements.

See quaternion_transforms.py for conventions used for quaternions.

NOTE: All angles are in radians.
"""

import numpy as np
import quaternion

from PiFinder.pointing_model.astro_coords import RaDecRoll
import PiFinder.pointing_model.quaternion_transforms as qt


class ImuDeadReckoning:
    """
    Use the plate-solved coordinates and IMU measurements to estimate the
    pointing using plate solving when available or dead-reckoning using the IMU
    when plate solving isn't available (e.g. when the scope is moving or
    between frames).

    For an explanation of the theory and conventions used, see
    PiFinder/pointing_model/README.md.

    This class uses the Equatorial frame as the reference and expects
    plate-solved coordinates in (ra, dec).

    All angles are in radians. None is not allowed as inputs (use np.nan).

    EXAMPLE:
    # Set up:
    imu_dead_reckoning = ImuDeadReckoning('flat')
    imu_dead_reckoning.set_alignment(solved_cam, solved_scope)

    # Update with plate solved and IMU data:
    imu_dead_reckoning.update_plate_solve_and_imu(solved_cam, q_x2imu)

    # Dead-reckoning using IMU
    imu_dead_reckoning.update_imu(q_x2imu)
    """

    # Alignment:
    q_cam2scope: quaternion.quaternion
    # IMU orientation:
    q_imu2cam: quaternion.quaternion
    q_cam2imu: quaternion.quaternion
    # Putting them together:
    q_imu2scope: quaternion.quaternion

    # The poinging of the camera and scope frames wrt the Equatorial frame.
    # These get updated by plate solving and IMU dead-reckoning.
    q_eq2cam: quaternion.quaternion

    # True when q_eq2cam is estimated by IMU dead-reckoning.
    # False when set by plate solving
    dead_reckoning: bool = False
    tracking: bool = False  # True when previous plate solve exists and is tracking

    # The IMU's unkonwn drifting reference frame X. This is solved for
    # every time we have a simultaneous plate solve and IMU measurement.
    q_eq2x: quaternion.quaternion = quaternion.quaternion(np.nan)  # nan means not set

    def __init__(self, screen_direction: str):
        """ """
        # IMU-to-camera orientation. Fixed by PiFinder type
        self._set_screen_direction(screen_direction)

    def set_alignment(self, solved_cam: RaDecRoll, solved_scope: RaDecRoll):
        """
        Set the alignment between the PiFinder camera center and the scope
        pointing.

        INPUTS:
        solved_cam: Equatorial coordinate of the camera center at alignment.
        solved_scope: Equatorial coordinate of the scope center at alignement.
        """
        # Calculate q_scope2cam (alignment)
        q_eq2cam = qt.get_q_eq(solved_cam.ra, solved_cam.dec, solved_cam.roll)
        q_eq2scope = qt.get_q_eq(solved_scope.ra, solved_scope.dec, solved_scope.roll)
        q_scope2cam = q_eq2scope.conjugate() * q_eq2cam

        # Set the alignmen attributes:
        self.q_cam2scope = q_scope2cam.normalized().conj()
        self.q_imu2scope = self.q_imu2cam * self.q_cam2scope

    def update_plate_solve_and_imu(
        self,
        solved_cam: RaDecRoll,
        q_x2imu: quaternion.quaternion,
    ):
        """
        Update the state with the az/alt measurements from plate solving in the
        camera frame. If the IMU measurement (which should be taken at the same
        time) is available, q_x2imu (the unknown drifting reference frame) will
        be solved for.

        INPUTS:
        solved_cam: RA/Dec/Roll of the camera pointing from plate solving.
        q_x2imu: [quaternion] Raw IMU measurement quaternions. This is the IMU
            frame orientation wrt unknown drifting reference frame X.
        """
        if not solved_cam.is_set:
            return  # No update

        # Update plate-solved coord: Camera frame relative to the Equatorial
        # frame where the +y camera frame (i.e. "up") points to the North
        # Celestial Pole (NCP) -- i.e. zero roll offset:
        self.q_eq2cam = qt.get_q_eq(solved_cam.ra, solved_cam.dec, solved_cam.roll)
        self.dead_reckoning = False  # Using plate solve, no dead_reckoning

        # Update IMU: Calculate the IMU's unknown reference frame X using the
        # plate solved coordinates and IMU measurements taken from the same
        # time. If the IMU measurement isn't provided (i.e. None), the existing
        # q_hor2x will continue to be used.
        if not np.isnan(q_x2imu):
            self.q_eq2x = self.q_eq2cam * self.q_cam2imu * q_x2imu.conj()
            self.q_eq2x = self.q_eq2x.normalized()
            self.tracking = True  # We have a plate solve and IMU measurement

    def update_imu(self, q_x2imu: quaternion.quaternion):
        """
        Update the state with the raw IMU measurement. Does a dead-reckoning
        estimate of the camera and scope pointing.

        INPUTS:
        q_x2imu: Quaternion of the IMU orientation w.r.t. an unknown and drifting
            reference frame X used by the IMU.
        """
        if not np.isnan(self.q_eq2x):
            # Dead reckoning estimate by IMU if q_hor2x has been estimated by a
            # previous plate solve.
            self.q_eq2cam = self.q_eq2x * q_x2imu * self.q_imu2cam
            self.q_eq2cam = self.q_eq2cam.normalized()

            self.q_eq2scope = self.q_eq2cam * self.q_cam2scope
            self.q_eq2scope = self.q_eq2scope.normalized()

            self.dead_reckoning = True

    def get_cam_radec(self) -> RaDecRoll:
        """
        Returns the (ra, dec, roll) of the camera centre and a Boolean
        dead_reckoning to indicate if the estimate is from dead-reckoning
        (True) or from plate solving (False).
        """
        ra_dec_roll = RaDecRoll()
        ra_dec_roll.set_from_quaternion(self.q_eq2cam)

        return ra_dec_roll

    def get_scope_radec(self) -> RaDecRoll:
        """
        Returns the (ra, dec, roll) of the scope and a Boolean dead_reckoning
        to indicate if the estimate is from dead-reckoning (True) or from plate
        solving (False).
        """
        ra_dec_roll = RaDecRoll()
        ra_dec_roll.set_from_quaternion(self.q_eq2scope)

        return ra_dec_roll

    def reset(self):
        """
        Resets the internal state.
        """
        self.q_eq2x = None
        self.tracking = False

    def _set_screen_direction(self, screen_direction: str):
        """
        Sets the screen direction which determines the fixed orientation between
        the IMU and camera (q_imu2cam).
        """
        self.q_imu2cam = get_screen_direction_q_imu2cam(screen_direction)
        self.q_cam2imu = self.q_imu2cam.conj()


def get_screen_direction_q_imu2cam(screen_direction: str) -> quaternion.quaternion:
    """
    Returns the quaternion that rotates the IMU frame to the camera frame
    based on the screen direction.

    INPUTS:
    screen_direction: "flat" or "upright"

    RETURNS:
    q_imu2cam: Quaternion that rotates the IMU frame to the camera frame.
    """
    if screen_direction == "left":
        # Left:
        # Rotate 90° around x_imu so that z_imu' points along z_camera
        q1 = qt.axis_angle2quat([1, 0, 0], np.pi / 2)
        # Rotate 90° around z_imu' to align with the camera cooridnates
        q2 = qt.axis_angle2quat([0, 0, 1], np.pi / 2)
        q_imu2cam = (q1 * q2).normalized()
    elif screen_direction == "right":
        # Right:
        # Rotate -90° around y_imu so that z_imu' points along z_camera
        q1 = qt.axis_angle2quat([0, 1, 0], np.pi / 2)
        # Rotate 90° around z_imu' to align with the camera cooridnates
        q2 = qt.axis_angle2quat([0, 0, 1], -np.pi / 2)
        q_imu2cam = (q1 * q2).normalized()
    elif screen_direction == "straight":
        # Straight:
        # Rotate 180° around y_imu so that z_imu' points along z_camera
        q1 = qt.axis_angle2quat([0, 1, 0], np.pi / 2)
        # Rotate -90° around z_imu' to align with the camera cooridnates
        q2 = qt.axis_angle2quat([0, 0, 1], -np.pi / 2)
        q_imu2cam = (q1 * q2).normalized()
    elif screen_direction == "flat3":
        # Flat v3:
        # Camera is tilted a further 30° compared to Flat v2
        # Rotate -120° around y_imu so that z_imu' points along z_camera
        q1 = qt.axis_angle2quat([0, 1, 0], -np.pi * 2 / 3)
        # Rotate -90° around z_imu' to align with the camera cooridnates
        q2 = qt.axis_angle2quat([0, 0, 1], -np.pi / 2)
        q_imu2cam = (q1 * q2).normalized()
    elif screen_direction == "flat":
        # Flat v2:
        # Rotate -90° around y_imu so that z_imu' points along z_camera
        q1 = qt.axis_angle2quat([0, 1, 0], -np.pi / 2)
        # Rotate -90° around z_imu' to align with the camera cooridnates
        q2 = qt.axis_angle2quat([0, 0, 1], -np.pi / 2)
        q_imu2cam = (q1 * q2).normalized()
    elif screen_direction == "as_dream":  # TODO: Propose to rename to "back"?
        # As Dream:
        # Camera points back up from the screen
        # NOTE: Need to check if the orientation of the camera is correct
        # Rotate +90° around z_imu to align with the camera cooridnates
        # (+y_cam is along -x_imu)
        q_imu2cam = qt.axis_angle2quat([0, 0, 1], +np.pi / 2)
    else:
        raise ValueError(f"Unsupported screen_direction: {screen_direction}")

    return q_imu2cam
