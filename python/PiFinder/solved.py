"""
Initialized 'solved' dictionary used by the solver and integrator.

Kept in its own module (rather than in solver.py) so that the dict shape
can be imported without dragging in the tetra3 submodule, which is not
available in CI environments that don't initialize git submodules.
"""


def get_initialized_solved_dict() -> dict:
    """
    Returns an initialized 'solved' dictionary with coordinate and other
    information.

    TODO: Update solver_main.py with this
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
        # Alt, Az [deg] of scope:
        "Alt": None,
        "Az": None,
        # Diagnostics:
        "solve_source": None,  # Source of the solve ("CAM", "CAM_FAILED", "IMU")
        "solve_time": None,
        "cam_solve_time": 0,
        "last_solve_attempt": 0,  # Timestamp of last solve attempt - tracks exposure_end of last processed image
        "last_solve_success": None,  # Timestamp of last successful solve
        "constellation": None,
    }

    return solved
