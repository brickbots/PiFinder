"""
Various astronomical coordinates functions
"""

import numpy as np
from typing import Union  # When updated to Python 3.10+, remove and use new type hints


class RaDecRoll():
    """
    Data class for equatorial coordinates defined by (RA, Dec, Roll).
    
    NOTE: All angles are in radians.
    """

    def __init__(self):
        """ """
        self.ra = None
        self.dec = None
        self.roll = None

    def set(self, ra: float, dec:float, roll: Union[float, None]):
        """ """
        self.ra = ra
        self.dec = dec
        self.roll = roll

    def set_from_deg(self, ra_deg, dec_deg, roll_deg):
        """ """
        if roll_deg is None:
            roll = None
        else:
            roll = np.deg2rad(roll_deg)

        self.set(np.deg2rad(ra_deg), np.deg2rad(dec_deg), roll)
        

