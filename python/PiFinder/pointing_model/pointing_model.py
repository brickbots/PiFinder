"""
Pointing model functions.

The quaternions use the notation in the form `q_a2b` for a quaternion that
rotates frame `a` to frame `b` using intrinsic rotation (by post-multiplying the
quaternions). For example:

q_a2c = q_a2b * q_a2c

NOTE: 

* All angles are in radians.
* The quaternions use numpy quaternions and are scalar-first.
* Some of the constant quaternion terms can be speeded up by not using 
trigonometric functions.
* The methods do not normalize the quaternions because this incurs a small 
computational overhead. Normalization should be done manually as and when 
necessary.
"""
from typing import Union  # When updated to Python 3.10+, remove and use new type hints
import numpy as np
import quaternion


def axis_angle2quat(axis, theta):
    """
    Convert from axis-angle representation to a quaternion

    INPUTS:
    axis: (3,) Axis of rotation (doesn't need to be a unit vector)
    angle: Angle of rotation [rad]
    """
    assert(len(axis) == 3, 'axis should be a list or numpy array of length 3.')
    # Define the vector part of the quaternion
    v = np.array(axis) / np.linalg.norm(axis) * np.sin(theta / 2)

    return np.quaternion(np.cos(theta / 2), v[0], v[1], v[2])



def get_q_hor2frame(az, alt):
    """ 
    Returns the quaternion to rotate from the horizontal frame to the frame
    (typically scope) at coordinates (az, alt) for an ideal AltAz mount.

    INPUTS:
    az: [rad] Azimuth of scope axis
    alt: [rad] Alt of scope axis
    """
    q_az = axis_angle2quat([0, 0, 1], -(az + np.pi / 2))
    q_alt = axis_angle2quat([1, 0, 0], (np.pi / 2 - alt))
    return q_az * q_alt


def get_azalt_of_q_hor2frame(q_hor2frame):
    """
    Returns the (az, alt) pointing of the frame which is defined by the z axis
    of the q_hor2frame quaternion.

    RETURNS:
    az: [rad]
    alt: [rad]
    """
    pz = np.quaternion(0, 0, 0, 1)  # Vector z represented as a pure quaternion
    frame_axis = q_hor2frame * pz * q_hor2frame.conj()  # Returns a pure quaternion along scope axis

    alt = np.pi / 2 - np.arccos(frame_axis.z)
    az = np.pi - np.arctan2(frame_axis.y, frame_axis.x)

    return az, alt


def get_quat_angular_diff(q1, q2):
    """
    Calculates the relative rotation between quaternions `q1` and `q2`.
    Accounts for the double-cover property of quaternions so that if q1 and q2
    are close, you get small angle d_theta rather than something around 2 * np.pi.
    """
    dq = q1.conj() * q2
    d_theta = 2 * np.arctan2(np.linalg.norm(dq.vec), dq.w)  # atan2 is more robust than using acos

    # Account for double cover where q2 = -q1 gives d_theta = 2 * pi
    if d_theta > np.pi:
        d_theta = 2 * np.pi - d_theta
    
    return d_theta  # In radians


class ImuDeadReckoning():
    """
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
    az, alt = get_azalt_of_q_hor2frame(q_hor2scope)
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
            q_hor2cam_up = get_q_hor2frame(solved_cam_az, solved_cam_alt)
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
        az_cam, alt_cam = get_azalt_of_q_hor2frame(self.q_hor2cam)
        return az_cam, alt_cam, self.dead_reckoning  # Angles are in radians

    def get_scope_azalt(self):
        """ """
        NotImplementedError()

    def reset(self):
        """
        Resets the internal state.
        """
        self.q_hor2x = None

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
