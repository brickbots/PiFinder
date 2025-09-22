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

import numpy as np
import quaternion


def axis_angle2quat(axis, theta: float) -> quaternion.quaternion:
    """
    Convert from axis-angle representation to a quaternion

    INPUTS:
    axis: (3,) Axis of rotation (doesn't need to be a unit vector)
    angle: Angle of rotation [rad]
    """
    assert len(axis) == 3, "axis should be a list or numpy array of length 3."
    # Define the vector part of the quaternion
    v = np.array(axis) / np.linalg.norm(axis) * np.sin(theta / 2)

    return quaternion.quaternion(np.cos(theta / 2), v[0], v[1], v[2])


def get_quat_angular_diff(
    q1: quaternion.quaternion, q2: quaternion.quaternion
) -> float:
    """
    Calculates the relative rotation between quaternions `q1` and `q2`.
    Accounts for the double-cover property of quaternions so that if q1 and q2
    are close, you get small angle d_theta rather than something around 2 * np.pi.
    """
    dq = q1.conj() * q2
    d_theta = 2 * np.arctan2(
        np.linalg.norm(dq.vec), dq.w
    )  # atan2 is more robust than using acos

    # Account for double cover where q2 = -q1 gives d_theta = 2 * pi
    if d_theta > np.pi:
        d_theta = 2 * np.pi - d_theta

    return d_theta  # In radians


# ========== Equatorial frame functions ============================


def get_q_eq(ra_rad: float, dec_rad: float, roll_rad: float) -> quaternion.quaternion:
    """
    Express the equatorial coordinates (RA, Dec, Roll) in radians
    in a quaternion rotation the relative to the Equatorial frame.
    """
    # Intrinsic rotation of q_ra followed by q_dec gives a quaternion rotation
    # that points +z towards the boresight of the camera. +y to the left and
    # +x down.
    q_ra = axis_angle2quat([0, 0, 1], ra_rad)  # Rotate frame around z (NCP)
    q_dec = axis_angle2quat([0, 1, 0], np.pi / 2 - dec_rad)  # Rotate around y'

    # Need to rotate this +90 degrees around z_cam so that +y_cam points up
    # and +x_cam points to the left of the Camera frame. In addition, need to
    # account for the roll offset of the camera (zero if +y_cam points up along
    # the great circle towards the NCP)
    q_roll = axis_angle2quat([0, 0, 1], np.pi / 2 + roll_rad)

    # Intrinsic rotation:
    q_eq = (q_ra * q_dec * q_roll).normalized()
    return q_eq


def get_radec_of_q_eq(q_eq2frame: quaternion.quaternion) -> tuple[float, float, float]:
    """
    Returns the (ra, dec, roll) angles of the quaterion rotation relative to
    the equatorial frame.
    """
    # Pure quaternion along camera boresight
    pz_frame = q_eq2frame * quaternion.quaternion(0, 0, 0, 1) * q_eq2frame.conj()
    # Calculate RA, Dec from the camera boresight:
    dec = np.arcsin(pz_frame.z)
    ra = np.arctan2(pz_frame.y, pz_frame.x)

    # Pure quaternion along y_cam which points to NCP when roll = 0
    py_cam = q_eq2frame * quaternion.quaternion(0, 0, 1, 0) * q_eq2frame.conj()
    # Local East and North vectors (roll is the angle between py_cam and the north vector)
    vec_east = np.array([-np.sin(ra), np.cos(ra), 0])
    vec_north = np.array(
        [-np.sin(dec) * np.cos(ra), -np.sin(dec) * np.sin(ra), np.cos(dec)]
    )
    roll = -np.arctan2(np.dot(py_cam.vec, vec_east), np.dot(py_cam.vec, vec_north))

    return ra, dec, roll  # In radians
