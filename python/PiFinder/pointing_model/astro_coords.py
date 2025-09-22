"""
Various astronomical coordinates functions
"""

from dataclasses import dataclass
import numpy as np
import quaternion
from typing import Union  # When updated to Python 3.10+, remove and use new type hints


@dataclass
class RaDecRoll:
    """
    Data class for equatorial coordinates defined by (RA, Dec, Roll). This
    makes it easier for interfacing and convert between radians and degrees.

    The set methods allow values to be float or None but internally, None will
    be stored as np.nan so that the type is consistent. the get methods will
    return None if the value is np.nan.

    NOTE: All angles are in radians.
    """

    ra: float = np.nan
    dec: float = np.nan
    roll: float = np.nan
    is_set = False

    def reset(self):
        """Reset to unset state"""
        self.ra = np.nan
        self.dec = np.nan
        self.roll = np.nan
        self.is_set = False

    def set(
        self, ra: Union[float, None], dec: Union[float, None], roll: Union[float, None]
    ):
        """Set using radians"""
        self.ra = ra if ra is not None else np.nan
        self.dec = dec if dec is not None else np.nan
        self.roll = roll if roll is not None else np.nan
        self.is_set = True

    def set_from_deg(
        self,
        ra_deg: Union[float, None],
        dec_deg: Union[float, None],
        roll_deg: Union[float, None],
    ):
        """Set using degrees"""
        ra = np.deg2rad(ra_deg) if ra_deg is not None else np.nan
        dec = np.deg2rad(dec_deg) if dec_deg is not None else np.nan
        roll = np.deg2rad(roll_deg) if roll_deg is not None else np.nan

        self.set(ra, dec, roll)

    def set_from_quaternion(self, q_eq: quaternion.quaternion):
        """
        Set from a quaternion rotation relative to the Equatorial frame.
        Re-using code from quaternion_transforms.get_radec_of_q_eq.
        """
        # Pure quaternion along camera boresight
        pz_frame = q_eq * quaternion.quaternion(0, 0, 0, 1) * q_eq.conj()

        # Calculate RA, Dec from the camera boresight:
        dec = np.arcsin(pz_frame.z)
        ra = np.arctan2(pz_frame.y, pz_frame.x)

        # Calcualte Roll:
        # Pure quaternion along y_cam which points to NCP when roll = 0
        py_cam = q_eq * quaternion.quaternion(0, 0, 1, 0) * q_eq.conj()
        # Local East and North vectors (roll is the angle between py_cam and the north vector)
        vec_east = np.array([-np.sin(ra), np.cos(ra), 0])
        vec_north = np.array(
            [-np.sin(dec) * np.cos(ra), -np.sin(dec) * np.sin(ra), np.cos(dec)]
        )
        roll = -np.arctan2(np.dot(py_cam.vec, vec_east), np.dot(py_cam.vec, vec_north))

        self.set(ra, dec, roll)

    def get(
        self, use_none=False
    ) -> tuple[Union[float, None], Union[float, None], Union[float, None]]:
        """
        Returns (ra, dec, roll) in radians.  If use_none is True, returns None
        for any unset (nan) values.
        """
        if use_none:
            ra = self.ra if not np.isnan(self.ra) else None
            dec = self.dec if not np.isnan(self.dec) else None
            roll = self.roll if not np.isnan(self.roll) else None
        else:
            ra, dec, roll = self.ra, self.dec, self.roll

        return ra, dec, roll

    def get_deg(
        self, use_none=False
    ) -> tuple[Union[float, None], Union[float, None], Union[float, None]]:
        """
        Returns (ra, dec, roll) in degrees. If use_none is True, returns None
        for any unset (nan) values.
        """
        if use_none:
            ra = np.rad2deg(self.ra) if not np.isnan(self.ra) else None
            dec = np.rad2deg(self.dec) if not np.isnan(self.dec) else None
            roll = np.rad2deg(self.roll) if not np.isnan(self.roll) else None
        else:
            ra, dec, roll = (
                np.rad2deg(self.ra),
                np.rad2deg(self.dec),
                np.rad2deg(self.roll),
            )

        return ra, dec, roll


def initialized_solved_dict() -> dict:
    """
    Returns an initialized 'solved' dictionary with cooridnate and other
    information.

    TODO: The solved dict is used by other components. Move this func
    and use this elsewhere (e.g. solver.py) to enforce consistency.
    TODO: use RaDecRoll class for the RA, Dec, Roll coordinates here?
    """
    # TODO: This dict is duplicated in solver.py - Refactor?
    # "Alt" and "Az" could be removed once we move to Eq-based dead-reckoning
    solved = {
        # RA, Dec, Roll of the scope at the target pixel
        "RA": None,
        "Dec": None,
        "Roll": None,
        # RA, Dec, Roll solved at the center of the camera FoV
        # update by the IMU in the integrator
        "camera_center": {
            "RA": None,
            "Dec": None,
            "Roll": None,
            "Alt": None,  # NOTE: Altaz needed by catalogs for altaz mounts
            "Az": None,
        },
        # RA, Dec, Roll from the camera, not updated by IMU in integrator
        "camera_solve": {
            "RA": None,
            "Dec": None,
            "Roll": None,
        },
        "imu_quat": None,  # IMU quaternion as numpy quaternion (scalar-first)
        "Alt": None,  # Alt of scope
        "Az": None,
        "solve_source": None,
        "solve_time": None,
        "cam_solve_time": 0,
        "constellation": None,
    }

    return solved
