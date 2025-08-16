"""
Various astronomical coordinates functions
"""

import numpy as np
from typing import Union  # When updated to Python 3.10+, remove and use new type hints


def get_initialized_solved_dict() -> dict:
    """
    Returns an initialized 'solved' dictionary with cooridnate and other 
    information.

    TODO: The solved dict is used by other components. Move this func
    and use this elsewhere (e.g. solver.py) to enforce consistency.
    """
    # TODO: This dict is duplicated in solver.py - Refactor?
    # "Alt" and "Az" could be removed once we move to Eq-based dead-reckoning
    solved = {
        "RA": None,  # RA of scope
        "Dec": None,
        "Roll": None,
        "camera_center": {
            "RA": None,
            "Dec": None,
            "Roll": None,
            "Alt": None,  # TODO: Remove Alt, Az keys later?
            "Az": None,
        },
        "camera_solve": {  # camera_solve is NOT updated by IMU dead-reckoning  
            "RA": None,
            "Dec": None,
            "Roll": None,
        },
        "Roll_offset": 0,  # May/may not be needed - for experimentation
        "imu_pos": None,
        "imu_quat": None,  # IMU quaternion as numpy quaternion (scalar-first) - TODO: Move to "imu"
        "Alt": None,  # Alt of scope
        "Az": None,
        "solve_source": None,
        "solve_time": None,
        "cam_solve_time": 0,
        "constellation": None,
    }
    
    return solved


class RaDecRoll():
    """
    Concept data class for equatorial coordinates defined by (RA, Dec, Roll).
    TODO: Migrate to something like this from the current "solved" dict?
    
    NOTE: All angles are in radians.
    """

    def __init__(self):
        """ """
        self.ra = None
        self.dec = None
        self.roll = None

    def set(self, ra:float, dec:float, roll:Union[float, None]):
        """ """
        self.ra = ra
        self.dec = dec
        self.roll = roll

    def set_from_deg(self, ra_deg:float, dec_deg:float, roll_deg:float):
        """ """
        if roll_deg is None:
            roll = None
        else:
            roll = np.deg2rad(roll_deg)

        self.set(np.deg2rad(ra_deg), np.deg2rad(dec_deg), roll)
        
    def get(self) -> (foat, float, float):
        """ """
        return self.ra, self.dec, self.roll

    def get_deg(self) -> (float, float, float):
        """ """
        return np.rad2deg(self.ra), np.rad2deg(self.dec), np.rad2deg(self.roll)
