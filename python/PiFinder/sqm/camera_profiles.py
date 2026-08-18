"""Back-compat re-export of the camera profiles.

Camera profiles moved to :mod:`PiFinder.camera_profiles` when the optical
train was modelled: a profile describes the sensor, which is Camera-context
vocabulary, and SQM is only one of several consumers of it (the solver's FOV
gate and the chart's frustum shading are others). Archived analysis scripts
and notebooks import from here, so the old path keeps working.

New code should import from :mod:`PiFinder.camera_profiles`, or from
:mod:`PiFinder.optics` if it wants a field of view -- that needs a lens as
well, and no profile carries one.
"""

from PiFinder.camera_profiles import (  # noqa: F401
    CAMERA_PROFILES,
    CameraProfile,
    detect_camera_type,
    get_camera_profile,
)

__all__ = [
    "CAMERA_PROFILES",
    "CameraProfile",
    "detect_camera_type",
    "get_camera_profile",
]
