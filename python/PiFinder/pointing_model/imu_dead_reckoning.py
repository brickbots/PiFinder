"""
IMU dead-reckoning extrapolates the scope pointing from the last plate-solved
coordinate using the IMU measurements.

See quaternion_transforms.py for conventions used for quaternions.

NOTE: All angles are in radians.
"""
from typing import Union  # When updated to Python 3.10+, remove and use new type hints
import numpy as np
import quaternion

from PiFinder.pointing_model.astro_coords import RaDecRoll
import PiFinder.pointing_model.quaternion_transforms as qt


class ImuDeadReckoning():
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
    imu_dead_reckoning.set_alignment(q_scope2cam)
    
    # Update with plate solved and IMU data:
    imu_dead_reckoning.update_plate_solve_and_imu(solved_cam_ra, solved_cam_dec, solved_cam_roll, q_x2imu)
    
    # Dead-reckoning using IMU
    imu_dead_reckoning.update_imu(q_x2imu)
    """
    # Alignment:
    q_scope2cam: np.quaternion  # ****Do we need this??
    q_cam2scope: np.quaternion
    # IMU orientation:
    q_imu2cam: np.quaternion
    q_cam2imu: np.quaternion
    # Putting them together:
    q_imu2scope: np.quaternion

    # The poinging of the camera and scope frames wrt the Equatorial frame.
    # These get updated by plate solving and IMU dead-reckoning.
    q_eq2cam: np.quaternion  # ***Do we need to keep q_eq2cam?

    # True when q_eq2cam is estimated by IMU dead-reckoning. 
    # False when set by plate solving
    dead_reckoning: bool = False  
    tracking: bool = False  # True when previous plate solve exists and tracking

    # The IMU's unkonwn drifting reference frame X. This is solved for 
    # every time we have a simultaneous plate solve and IMU measurement.
    q_eq2x: np.quaternion = np.quaternion(np.nan)  # nan means not set


    def __init__(self, screen_direction:str):
        """ """
        # IMU-to-camera orientation. Fixed by PiFinder type
        self._set_screen_direction(screen_direction)
    
    def set_alignment(self, 
                      q_scope2cam: np.quaternion): 
        """
        Set the alignment between the PiFinder camera center and the scope
        pointing.

        TODO: Setting cam2scope might be more natural?

        INPUTS:
        q_scope2cam: Quaternion that rotates the scope frame to the camera frame.
        """
        # TODO: Use qt.get_q_scope2cam(target_eq, cam_eq)
        self.q_scope2cam = q_scope2cam.normalized()
        self.q_cam2scope = self.q_scope2cam.conj()
        self.q_imu2scope = self.q_imu2cam * self.q_cam2scope

    def update_plate_solve_and_imu(self, solved_cam_ra: float, 
                                   solved_cam_dec: float, 
                                   solved_cam_roll: float, 
                                   q_x2imu: np.quaternion):
        """ 
        Update the state with the az/alt measurements from plate solving in the
        camera frame. If the IMU measurement (which should be taken at the same 
        time) is available, q_x2imu (the unknown drifting reference frame) will
        be solved for. 

        INPUTS:
        solved_cam_az: [rad] Azimuth of the camera pointing from plate solving.
        solved_cam_alt: [rad] Alt of the camera pointing from plate solving.
        solved_cam_roll_offset: [rad] Roll offset of the camera frame +y ("up")
            relative to the pole.
        q_x2imu: [quaternion] Raw IMU measurement quaternions. This is the IMU 
            frame orientation wrt unknown drifting reference frame X.
        """
        if np.isnan(solved_cam_ra) or np.isnan(solved_cam_dec):
            return  # No update
        
        # Update plate-solved coord: Camera frame relative to the Equatorial
        # frame where the +y camera frame (i.e. "up") points to the North
        # Celestial Pole (NCP) -- i.e. zero roll offset:
        self.q_eq2cam  = qt.get_q_eq2cam(solved_cam_ra, solved_cam_dec, 
                                         solved_cam_roll)
        self.dead_reckoning = False

        # Update IMU: Calculate the IMU's unknown reference frame X using the
        # plate solved coordinates and IMU measurements taken from the same
        # time. If the IMU measurement isn't provided (i.e. None), the existing
        # q_hor2x will continue to be used.
        if not np.isnan(q_x2imu):
            self.q_eq2x = self.q_eq2cam * self.q_cam2imu * q_x2imu.conj()
            self.q_eq2x = self.q_eq2x.normalized()
            self.tracking = True  # We have a plate solve and IMU measurement

    def update_imu(self, 
                   q_x2imu: np.quaternion):
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

    def get_cam_radec(self) -> tuple[float, float, float, bool]:
        """ 
        Returns the (ra, dec, roll) of the camera and a Boolean dead_reckoning
        to indicate if the estimate is from dead-reckoning (True) or from plate
        solving (False).
        """
        ra, dec, roll = qt.get_radec_of_q_eq(self.q_eq2cam)
        return ra, dec, roll  # Angles are in radians

    def get_scope_radec(self) -> tuple[float, float, float, bool]:
        """ 
        Returns the (ra, dec, roll) of the scope and a Boolean dead_reckoning
        to indicate if the estimate is from dead-reckoning (True) or from plate
        solving (False).
        """
        ra, dec, roll = qt.get_radec_of_q_eq(self.q_eq2scope)
        return ra, dec, roll  # Angles are in radians

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


def get_screen_direction_q_imu2cam(screen_direction: str) -> np.quaternion:
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
        # Rotate -XX° around y_imu so that z_imu' points along z_camera
        q1 = qt.axis_angle2quat([0, 1, 0], -np.pi / 2) 
        # Rotate -90° around z_imu' to align with the camera cooridnates
        q2 = qt.axis_angle2quat([0, 0, 1], -np.pi / 2)
        q_imu2cam = (q1 * q2).normalized()
        raise ValueError('Unsupported screen_direction: flat3')  # TODO: Update the unknown tilt and remove this
    elif screen_direction == "flat":
        # Flat v2:
        # Rotate -90° around y_imu so that z_imu' points along z_camera
        q1 = qt.axis_angle2quat([0, 1, 0], -np.pi / 2) 
        # Rotate -90° around z_imu' to align with the camera cooridnates
        q2 = qt.axis_angle2quat([0, 0, 1], -np.pi / 2)
        q_imu2cam = (q1 * q2).normalized()
    elif screen_direction == "as_dream":
        raise ValueError('Unsupported screen_direction: as_dream')
    else:
        raise ValueError(f'Unsupported screen_direction: {screen_direction}')
    
    return q_imu2cam
