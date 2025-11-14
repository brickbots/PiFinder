"""
Various astronomical coordinates functions
"""

from dataclasses import dataclass
import numpy as np
import quaternion
from typing import Union  # When updated to Python 3.10+, remove and use new type hints

import PiFinder.pointing_model.quaternion_transforms as qt


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
        Re-using code from quaternion_transforms.q_eq2radec.
        """
        ra, dec, roll = qt.q_eq2radec(q_eq)
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

    TODO: use RaDecRoll class for the RA, Dec, Roll coordinates here?
    TODO: "Alt" and "Az" could be removed but seems to be required by catalogs?
    """
    solved = {
        # RA, Dec, Roll [deg] of the scope at the target pixel
        "RA": None,
        "Dec": None,
        "Roll": None,
        # RA, Dec, Roll [deg] solved at the center of the camera FoV
        # update by the IMU in the integrator
        "camera_center": {
            "RA": None,
            "Dec": None,
            "Roll": None,
            "Alt": None,  # NOTE: Altaz needed by catalogs for altaz mounts
            "Az": None,
        },
        # RA, Dec, Roll [deg] from the camera, not updated by IMU in integrator
        "camera_solve": {
            "RA": None,
            "Dec": None,
            "Roll": None,
        },
        "imu_quat": None,  # IMU quaternion as numpy quaternion (scalar-first)
        # Alt, Az [deg] of scope
        "Alt": None,
        "Az": None,
        "solve_source": None,
        "solve_time": None,
        "cam_solve_time": 0,
        "constellation": None,
    }

    return solved
