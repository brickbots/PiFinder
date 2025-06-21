"""
Pointing model functions.

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

# Mount type enumerations
mount_type_altaz = 1
mount_type_gem = 2


def get_q_horiz2mnt_altaz_mount():
    """
    Quaternion rotation from horizontal to the mount frame for a perfect
    altaz mount. 

    For a perfect altaz mount, y_mnt points to zenith (+z_hor), z_mnt points North (-x_hor) and 
    x_mnt points West (-y_hor).
    """
    q_horiz2mnt = np.quaternion(np.cos(np.pi / 4), 0, 0, np.sin(np.pi / 4)) \
        * np.quaternion(np.cos(np.pi / 4), np.sin(np.pi / 4), 0, 0) * np.quaternion(0, 0, 1, 0)
    return q_horiz2mnt


def get_q_horiz2mnt_equatorial_mount(lat):
    """ 
    Returns the quaternion to rotate from the Horizontal frame to the equatorial
    frame for a perfect equatorial mount.
    """
    colat = np.pi / 2 - lat
    # Rotate 90° around x_hor so that y' points to zenith
    q1 = np.quaternion(np.cos(np.pi / 4), np.sin(np.pi / 4), 0, 0)  
    # Tilt so that y_mnt points to north polse
    q2 = np.quaternion(np.cos(colat / 2), 0, 0, np.sin(colat / 2)) 

    q_horiz2mnt = q1 * q2  # Intrinsic rotation: q1 followed by q2

    return q_horiz2mnt


def get_q_mnt_error_for_altaz_mount(az_err=0, alt_err=0):
    """
    Returns the mount error for an altaz mount.

    PARAMETERS:
    az_err: +ve rotates the mount around z_hor from North to East.
    alt_err: +ve rotates the mount around y_hor (West-East axis) towards North.
    """
    NotImplementedError()


def get_q_mnt_error_for_equatorial_mount(ra_err=0, dec_err=0):
    """
    Returns the mount error for an equatorial mount.

    PARAMETERS:
    """
    NotImplementedError()


def get_q_mnt2gimb(gimb_az, gimb_alt):
    """" 
    Returns the quaternion to rotate from the Mount frame to the Gimbal frame
    by the specified gimbal rotations. This assumes that the gimbals are 
    perpendicular. Later, non-perpendicularity will be incorporated here.

    INPUTS:
    gimb_az: Gimbal rotation angle around y_mnt. +ve angle is a clockwise 
        rotation when looking down along the y_mnt axis (i.e. towards -y_mnt).
    gimb_alt: Gimbal altitude angle. +ve angle is clockwise rotation around 
        when looking towards -x_mnt. 
    """
    # Step 1: Az: Rotate around the original az axis (y_mnt)
    q_gimb_az = np.quaternion(np.cos(-gimb_az / 2), 0, np.sin(-gimb_az / 2), 0)
    # Step 2: Alt: Rotate around the new alt axis (x_mnt')
    q_gimb_alt = np.quaternion(np.cos(-gimb_alt / 2), np.sin(-gimb_alt / 2), 0, 0)

    # Combine az rotation followed by alt rotation using intrinsic rotation
    # so that q_gimb_alt rotates the quaternion around the alt gimbal 
    # axis after rotation around the az axis.
    q_mnt2gimb = q_gimb_az * q_gimb_alt  # Intrinsic (az followed by alt)

    return q_mnt2gimb


def get_q_gimb2scope(mount_type):
    """" 
    Returns the quaternion to rotate from the Gimbal frame to the Scope frame.
    For the ideal case, the Scope frame is assumed to be the same as the Gimbal
    frame. 
    
    Misalignments and gravitational sag of the scope could be incroporated here.
    """
    if mount_type == mount_type_altaz:
        # Altaz
        q_gimb2scope = np.quaternion(1, 0, 0, 0)  # Invariant
    elif mount_type == mount_type_gem:
        # GEM
        q_gimb2scope = np.quaternion(np.cos(-np.pi / 4), 0, np.sin(-np.pi / 4), 0) \
            * np.quaternion(np.cos(-np.pi / 4), np.sin(-np.pi / 4), 0, 0)
        #q_gimb2scope = np.quaternion(np.cos(-np.pi / 4), 0, 0, np.sin(-np.pi / 4))
    else:
        raise ValueError()

    return q_gimb2scope


def get_q_scope2camera():
    """
    Returns the quaternion to rotate from the Scope frame to the Camera frame.
    """


def get_q_imu2camera():
    """ 
    Returns the quaternion to transform from the IMU frame to the Camera frame.  
    """
    # Rotate -90° around y_imu so that z_imu' points along z_camera
    q1 = np.quaternion(np.cos(-np.pi / 4), 0, np.sin(-np.pi / 4), 0)  
    # Rotate -90° around z_imu' to align with the camera cooridnates
    q2 = np.quaternion(np.cos(-np.pi / 4), 0, 0, np.sin(-np.pi / 4)) 
    q_imu2cam = q1 * q2  # Intrinsic rotation: q1 followed by q2

    return q_imu2cam


def get_q_camera2imu():
    """ 
    Returns the quaternion to transform from the Camera frame to the IMU frame.  
    """
    q_imu2cam = get_q_imu2camera()
    return q_imu2cam.conjugate()


def get_gimb_angles_altaz_mount(az, alt):
    """
    Returns the gimbal angles for an Altaz mount.

    EXAMPLE:
    gimb_az, gimb_alt = get_gimb_angles_altaz_mount(az, alt)
    """
    return az, alt  # Returns: gimb_az, gimb_alt


def get_gimb_angles_equatorial_mount(ha, dec):
    """
    Returns the gimbal angles for an EQ mount.

    EXAMPLE:
    gimb_az, gimb_alt = get_gimb_angles_equatorial_mount(ha, dec)
    """
    # Correct for East - for west, need to do a meridian flip??
    gimb_az = ha + np.pi / 2  # HA is clockwise, around z_mnt (looking down from +z_mnt)
    # Anti-clockwise turn around x_mnt increases dec
    # 
    # NOTE: For a GEM, when scope is on E side, an anti-clockwise turn will
    # decrease the dec
    gimb_alt = np.pi / 2 - dec 

    return gimb_az, gimb_alt

def get_q_horiz2scope(az, alt):
    """ 
    Returns the quaternion to rotate from the horizontal frame to the scope frame
    at coordinates (az, alt) for an ideal AltAz mount.

    INPUTS:
    az: [rad] Azimuth of scope axis
    alt: [rad] Alt of scope axis
    """
    return np.quaternion(np.cos(-(az + np.pi/2) / 2), 0, 0, np.sin(-(az + np.pi/2) / 2)) \
        * np.quaternion(np.cos((np.pi / 2 - alt) / 2), np.sin((np.pi / 2 - alt) / 2), 0, 0)
