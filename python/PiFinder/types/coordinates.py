"""
Astronomical coordinate types
"""

from dataclasses import dataclass
import numpy as np
import quaternion
from typing import Union  # When updated to Python 3.10+, remove and use new type hints

from PiFinder.pointing_model.quaternion_transforms import q_eq2radec, radec2q_eq


@dataclass
class RaDecRoll:
    """
    Data class for equatorial coordinates defined by (RA, Dec, Roll). This
    makes it easier for interfacing and convert between radians and degrees.

    The set methods allow values to be float or None but internally, None will
    be stored as np.nan so that the type is consistent. the get methods will
    return None if the value is np.nan.
    """
    ra: float = np.nan  # All angles in radians
    dec: float = np.nan
    roll: float = np.nan
    valid = False

    def __init__(self, ra: float, dec: float, roll: float, deg=False):
        self.set(ra, dec, roll, deg=deg)
    
    @classmethod
    def from_quaternion(cls, q_eq: quaternion.quaternion):
        ra, dec, roll = q_eq2radec(q_eq)
        return cls(ra, dec, roll)

    def reset(self):
        """Reset to unset state"""
        self.ra = np.nan
        self.dec = np.nan
        self.roll = np.nan
        self.valid = False
    
    def set(
        self, 
        ra: Union[float, None], 
        dec: Union[float, None], 
        roll: Union[float, None],
        deg=False  # If True, input angles are in degrees
    ):
        """Set using radians"""
        self.ra = ra if ra is not None else np.nan
        self.dec = dec if dec is not None else np.nan
        self.roll = roll if roll is not None else np.nan
        
        if np.isnan(self.ra) or np.isnan(self.dec) or np.isnan(self.roll):
            self.valid = False
        else:
            self.valid = True
        
        if deg:
            self.ra = np.deg2rad(self.ra)
            self.dec = np.deg2rad(self.dec)
            self.roll = np.deg2rad(self.roll)

    def set_from_quaternion(self, q_eq: quaternion.quaternion):
        """
        Set from a quaternion rotation relative to the Equatorial frame.
        """
        ra, dec, roll = q_eq2radec(q_eq)
        self.set(ra, dec, roll)

    def as_quaternion(self) -> quaternion.quaternion:
        """
        Return the quaternion rotation relative to the Equatorial frame.
        """
        return radec2q_eq(self.ra, self.dec, self.roll)

    def get(self, 
            use_none=True, # If True, returns None instead of np.nan
            deg=False  # If True, returns degrees
            ) -> tuple[Union[float, None], Union[float, None], Union[float, None]]:
        """
        Returns (ra, dec, roll) in radians.  If use_none is True, returns None
        for any unset (nan) values.
        """
        if deg:
            ra, dec, roll = np.rad2deg(self.ra), np.rad2deg(self.dec), np.rad2deg(self.roll)
        else:
            ra, dec, roll = self.ra, self.dec, self.roll

        if use_none:
            ra = ra if not np.isnan(ra) else None
            dec = dec if not np.isnan(dec) else None
            roll = roll if not np.isnan(roll) else None

        return ra, dec, roll


@dataclass
class RaDec:
    """
    Data class for equatorial coordinates defined by (RA, Dec).

    The set methods allow values to be float or None but internally, None will
    be stored as np.nan so that the type is consistent. the get methods will
    return None if the value is np.nan.
    """
    ra: float = np.nan  # All angles in radians
    dec: float = np.nan
    valid = False

    def __init__(self, ra: float, dec: float, roll: float, deg=False):
        raise NotImplementedError("Outline for RaDec class")
  

@dataclass
class AltAz:
    """
    Data class for horizontal coordinates defined by (Alt, Az).

    The set methods allow values to be float or None but internally, None will
    be stored as np.nan so that the type is consistent. the get methods will
    return None if the value is np.nan.
    """
    alt: float = np.nan  # All angles in radians
    az: float = np.nan
    valid = False

    def __init__(self, alt: float, az: float, deg=False):
        raise NotImplementedError("Outline for AltAz class")
