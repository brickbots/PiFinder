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
    
    @classmethod
    def set(
        cls, 
        ra: Union[float, None], 
        dec: Union[float, None], 
        roll: Union[float, None],
        deg=False  # If True, input angles are in degrees
    ):
        """Set using radians"""
        cls.ra = ra if ra is not None else np.nan
        cls.dec = dec if dec is not None else np.nan
        cls.roll = roll if roll is not None else np.nan
        cls.is_set = True
        if deg:
            cls.ra = np.deg2rad(cls.ra)
            cls.dec = np.deg2rad(cls.dec)
            cls.roll = np.deg2rad(cls.roll)

    @classmethod
    def set_from_quaternion(cls, q_eq: quaternion.quaternion):
        """
        Set from a quaternion rotation relative to the Equatorial frame.
        Re-using code from quaternion_transforms.q_eq2radec.
        """
        ra, dec, roll = qt.q_eq2radec(q_eq)
        cls.set(ra, dec, roll)

    def get(self, 
            use_none=True, # If True, returns None instead of np.nan
            deg=False  # If True, returns degrees
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

        if deg:
            return np.rad2deg(ra), np.rad2deg(dec), np.rad2deg(roll)
        else:
            return ra, dec, roll
