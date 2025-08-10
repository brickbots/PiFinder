"""
Pointing model functions.

See quaternion_transforms.py for conventions used for quaternions.

NOTE: All angles are in radians.
"""
from typing import Union  # When updated to Python 3.10+, remove and use new type hints
import numpy as np
import quaternion

import PiFinder.pointing_model.quaternion_transforms as qt


class ImuDeadReckoningHoriz():
    """
    Dead reckoning tracking using the IMU - wrt Horizontal frame

    Use the plate-solved coordinates and IMU measurements to estimate the
    pointing using plate solving when available or dead-reckoning using the IMU
    when plate solving isn't available (e.g. when the scope is moving or 
    between frames).

    All angles are in radians.

    HOW IT WORKS:
    The IMU quaternion measurements, q_x2imu, are relative to some arbitrary
    drifting frame X. This uses the latest plate solved coordinate with the
    latest IMU measurement to solve for the IMU's reference frame X. The frame
    X is expressed by the quaternion rotation q_hor2x from the Horizontal frame
    to X. Once we know q_hor2x, we can infer the camera pointing using the IMU
    data by dead reckoning: q_hor2cam = q_hor2x * q_x2imu * q_imu2cam

    EXAMPLE:
    # Set up:
    pointing_tracker = ImuDeadReckoning('flat')
    pointing_tracker.set_alignment(q_scope2cam)
    
    # Update with plate solved and IMU data:
    pointing_tracker.update_plate_solve_and_imu(solved_cam_az, solved_cam_alt, q_x2imu)
    q_hor2scope = pointing_tracker.get_q_hor2scope()
    
    # Dead-reckoning using IMU
    pointing_tracker.update_imu(q_x2imu)
    q_hor2scope = pointing_tracker.get_q_hor2scope()
    az, alt = pointing_tracker.get_cam_azalt()
    """

    def __init__(self, screen_direction):
        """ """
        # IMU-to-camera orientation. Fixed by PiFinder type
        self._set_screen_direction(screen_direction)

        # Alignment:
        self.q_scope2cam = None
        self.q_cam2scope = None

        # The poinging of the camera and scope frames wrt the horizontal frame.
        # These get updated by plate solving and IMU dead-reckoning.
        self.q_hor2cam = None

        # True when q_hor2cam is estimated by IMU dead-reckoning. 
        # False when set by plate solving
        self.dead_reckoning = False 
        self.tracking = False  # True when previous plate solve exists and tracking

        # The IMU's unkonwn drifting reference frame X. This is solved for 
        # every time we have a simultaneous plate solve and IMU measurement.
        self.q_hor2x = None
    
    def set_alignment(self, 
                      q_scope2cam: quaternion.quaternion):
        """
        Set the alignment between the PiFinder camera center and the scope
        pointing.

        INPUTS:
        q_scope2cam: Quaternion that rotates the scope frame to the camera frame.
        """
        self.q_scope2cam = q_scope2cam.normalized()
        self.q_cam2scope = self.q_scope2cam.conj()  

    def update_plate_solve_and_imu(self, 
                           solved_cam_az: Union[float, None], 
                           solved_cam_alt: Union[float, None], 
                           solved_cam_roll_offset: Union[float, None],
                           q_x2imu: Union[quaternion.quaternion, None]):
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
        if (solved_cam_az is None) or (solved_cam_alt is None):
            return  # No update
        else:
            # Camera frame relative to the horizontal frame where the +y camera
            # frame (i.e. "up") points to zenith:
            q_hor2cam_up = qt.get_q_hor2frame(solved_cam_az, solved_cam_alt)
            # Account for camera rotation around the +z camera frame 
            q_cam_rot_z = np.quaternion(np.cos(solved_cam_roll_offset / 2), 
                                        0, 0, np.sin(solved_cam_roll_offset / 2))
            # Combine (intrinsic rotation)
            self.q_hor2cam = (q_hor2cam_up * q_cam_rot_z).normalized()
            self.dead_reckoning = False

        # Calculate the IMU's unknown reference frame X using the plate solved 
        # coordinates and IMU measurements taken from the same time. If the IMU
        # measurement isn't provided (e.g. None or zeros), the existing q_hor2x
        # will continue to be used.
        if q_x2imu:
            self.q_hor2x = self.q_hor2cam * self.q_cam2imu * q_x2imu.conj()
            self.q_hor2x = self.q_hor2x.normalized()
            self.tracking = True  # We have a plate solve and IMU measurement

    def update_imu(self, 
                   q_x2imu: quaternion.quaternion):
        """
        Update the state with the raw IMU measurement. Does a dead-reckoning
        estimate of the camera and scope pointing.

        INPUTS:
        q_x2imu: Quaternion of the IMU orientation w.r.t. an unknown and drifting
            reference frame X used by the IMU.
        """
        if self.q_hor2x is not None:
            # Dead reckoning estimate by IMU if q_hor2x has been estimated by a 
            # previous plate solve.
            self.q_hor2cam = self.q_hor2x * q_x2imu * self.q_imu2cam
            self.q_hor2cam = self.q_hor2cam.normalized()

            self.dead_reckoning = True

    def get_q_hor2scope(self):
        """ """
        if self.q_hor2cam and self.q_cam2scope:
            q_hor2scope = self.q_hor2cam * self.q_cam2scope
            return q_hor2scope
        else:
            None

    def get_cam_azalt(self):
        """ 
        Returns the (az, alt) of the camera and a Boolean dead_reckoning to
        indicate if the estimate is from dead-reckoning (True) or from plate
        solving (False).
        """
        az_cam, alt_cam = qt.get_azalt_of_q_hor2frame(self.q_hor2cam)
        return az_cam, alt_cam, self.dead_reckoning  # Angles are in radians

    def get_scope_azalt(self):
        """ """
        NotImplementedError()

    def reset(self):
        """
        Resets the internal state.
        """
        self.q_hor2x = None
        self.tracking = False

    def _set_screen_direction(self, screen_direction: str):
        """
        Sets the screen direction which determines the fixed orientation between
        the IMU and camera (q_imu2cam).
        """
        if screen_direction == "flat":
            # Rotate -90° around y_imu so that z_imu' points along z_camera
            q1 = np.quaternion(np.cos(-np.pi / 4), 0, np.sin(-np.pi / 4), 0)  
            # Rotate -90° around z_imu' to align with the camera cooridnates
            q2 = np.quaternion(np.cos(-np.pi / 4), 0, 0, np.sin(-np.pi / 4)) 
            self.q_imu2cam = q1 * q2  # Intrinsic rotation: q1 followed by q2
        else:
            raise ValueError('Unsupported screen_direction')

        self.q_imu2cam = self.q_imu2cam.normalized()
        self.q_cam2imu = self.q_imu2cam.conj()


# ==== Equatorial frame version ====


class ImuDeadReckoningEqFrame():
    """
    Use the plate-solved coordinates and IMU measurements to estimate the
    pointing using plate solving when available or dead-reckoning using the IMU
    when plate solving isn't available (e.g. when the scope is moving or 
    between frames).
    
    This class uses the Equatorial frame as the reference and expect plate-solved
    coordinates in (ra, dec).

    All angles are in radians.

    HOW IT WORKS:

    EXAMPLE:
    # Set up:
    pointing_tracker = ImuDeadReckoningEqFrame('flat')
    pointing_tracker.set_alignment(q_scope2cam)
    
    # Update with plate solved and IMU data:
    pointing_tracker.update_plate_solve_and_imu(solved_cam_ra, solved_cam_dec, solved_cam_roll, q_x2imu)
    
    # Dead-reckoning using IMU
    pointing_tracker.update_imu(q_x2imu)
    """

    def __init__(self, screen_direction):
        """ """
        # Alignment:
        self.q_scope2cam = None  # ****Do we need this??
        self.q_cam2scope = None
        # IMU orientation:
        self.q_imu2cam = None
        self.q_cam2imu = None
        # IMU-to-camera orientation. Fixed by PiFinder type
        self._set_screen_direction(screen_direction)
        # Putting them together:
        self.q_imu2scope = None

        # The poinging of the camera and scope frames wrt the Equatorial frame.
        # These get updated by plate solving and IMU dead-reckoning.
        self.q_eq2cam = None  # ***Do we need to keep q_eq2cam?

        # True when q_eq2cam is estimated by IMU dead-reckoning. 
        # False when set by plate solving
        self.dead_reckoning = False  
        self.tracking = False  # True when previous plate solve exists and tracking

        # The IMU's unkonwn drifting reference frame X. This is solved for 
        # every time we have a simultaneous plate solve and IMU measurement.
        self.q_eq2x = None
    
    def set_alignment(self, 
                      q_scope2cam: quaternion.quaternion):
        """
        Set the alignment between the PiFinder camera center and the scope
        pointing.

        INPUTS:
        q_scope2cam: Quaternion that rotates the scope frame to the camera frame.
        """
        self.q_scope2cam = q_scope2cam.normalized()
        self.q_cam2scope = self.q_scope2cam.conj()
        self.q_imu2scope = self.q_imu2cam * self.q_cam2scope

    def update_plate_solve_and_imu(self, 
                           solved_cam_ra: Union[float, None], 
                           solved_cam_dec: Union[float, None], 
                           solved_cam_roll: Union[float, None],
                           q_x2imu: Union[quaternion.quaternion, None]):
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
        if (solved_cam_ra is None) or (solved_cam_dec is None):
            return  # No update
        else:
            # Update plate-solved coord:
            # Camera frame relative to the Equatorial frame where the +y camera
            # frame (i.e. "up") points to the North Celestial Pole (NCP) -- i.e. 
            # zero roll offset:
            self.q_eq2cam  = qt.get_q_eq2cam(solved_cam_ra, solved_cam_dec, solved_cam_roll)
            self.dead_reckoning = False

        # Update IMU:
        # Calculate the IMU's unknown reference frame X using the plate solved 
        # coordinates and IMU measurements taken from the same time. If the IMU
        # measurement isn't provided (e.g. None or zeros), the existing q_hor2x
        # will continue to be used.
        if q_x2imu:
            self.q_eq2x = self.q_eq2cam * self.q_cam2imu * q_x2imu.conj()
            self.q_eq2x = self.q_eq2x.normalized()
            self.tracking = True  # We have a plate solve and IMU measurement

    def update_imu(self, 
                   q_x2imu: quaternion.quaternion):
        """
        Update the state with the raw IMU measurement. Does a dead-reckoning
        estimate of the camera and scope pointing.

        INPUTS:
        q_x2imu: Quaternion of the IMU orientation w.r.t. an unknown and drifting
            reference frame X used by the IMU.
        """
        if self.q_eq2x is not None:
            # Dead reckoning estimate by IMU if q_hor2x has been estimated by a 
            # previous plate solve.
            self.q_eq2cam = self.q_eq2x * q_x2imu * self.q_imu2cam
            self.q_eq2cam = self.q_eq2cam.normalized()

            self.q_eq2scope = self.q_eq2cam * self.q_cam2scope
            self.q_eq2scope = self.q_eq2scope.normalized()

            self.dead_reckoning = True

    def get_q_eq2scope(self):
        """ """
        if self.q_eq2cam and self.q_cam2scope:
            q_eq2scope = self.q_eq2cam * self.q_cam2scope
            return q_eq2scope
        else:
            None

    def get_cam_radec(self):
        """ 
        Returns the (ra, dec, roll) of the camera and a Boolean dead_reckoning
        to indicate if the estimate is from dead-reckoning (True) or from plate
        solving (False).
        """
        ra, dec, roll = qt.get_radec_of_q_eq2cam(self.q_eq2cam)
        return ra, dec, roll, self.dead_reckoning  # Angles are in radians

    def get_scope_radec(self):
        """ 
        Returns the (ra, dec, roll) of the scope and a Boolean dead_reckoning
        to indicate if the estimate is from dead-reckoning (True) or from plate
        solving (False).
        """
        ra, dec, roll = qt.get_radec_of_q_eq2cam(self.q_eq2cam)
        return ra, dec, roll, self.dead_reckoning  # Angles are in radians

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
        if screen_direction == "flat":
            # Rotate -90° around y_imu so that z_imu' points along z_camera
            q1 = np.quaternion(np.cos(-np.pi / 4), 0, np.sin(-np.pi / 4), 0)  
            # Rotate -90° around z_imu' to align with the camera cooridnates
            q2 = np.quaternion(np.cos(-np.pi / 4), 0, 0, np.sin(-np.pi / 4)) 
            self.q_imu2cam = q1 * q2  # Intrinsic rotation: q1 followed by q2
        else:
            raise ValueError('Unsupported screen_direction')

        self.q_imu2cam = self.q_imu2cam.normalized()
        self.q_cam2imu = self.q_imu2cam.conj()
