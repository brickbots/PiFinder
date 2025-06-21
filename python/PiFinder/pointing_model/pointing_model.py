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

import numpy as np
import quaternion


def get_q_hor2scope(az, alt):
    """ 
    Returns the quaternion to rotate from the horizontal frame to the scope frame
    at coordinates (az, alt) for an ideal AltAz mount.

    INPUTS:
    az: [rad] Azimuth of scope axis
    alt: [rad] Alt of scope axis
    """
    return np.quaternion(np.cos(-(az + np.pi/2) / 2), 0, 0, np.sin(-(az + np.pi/2) / 2)) \
        * np.quaternion(np.cos((np.pi / 2 - alt) / 2), np.sin((np.pi / 2 - alt) / 2), 0, 0)


def get_altaz_from_q_hor2scope(q_hor2scope):
    """
    Returns the (az, alt) pointing of the scope which is defined by the z axis
    of the q_hor2scope quaternion.

    RETURNS:
    az: [rad]
    alt: [rad]
    """
    pz = np.quaternion(0, 0, 0, 1)  # Vector z represented as a pure quaternion
    scope_axis = q_hor2scope * pz * q_hor2scope.conj()  # Returns a pure quaternion along scope axis

    alt = np.pi / 2 - np.arccos(scope_axis.z)
    az = np.pi - np.arctan2(scope_axis.y, scope_axis.x)

    return az, alt