"""
Quaternion transformations

For quaternions, we use the notation `q_a2b`. This represents a quaternion that
rotates frame `a` to frame `b` using intrinsic rotation (by post-multiplying
the quaternions). This notation makes makes chains of intrinsic rotations
simple and clear. For example, this gives a quaternion `q_a2c` that rotates
from frame `a` to frame `c`:

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
    assert len(axis) == 3, 'axis should be a list or numpy array of length 3.'
    # Define the vector part of the quaternion
    v = np.array(axis) / np.linalg.norm(axis) * np.sin(theta / 2)

    return np.quaternion(np.cos(theta / 2), v[0], v[1], v[2])


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


# ========== Horizontal (altaz) frame functions ============================

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
