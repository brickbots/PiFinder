"""
SQM (Sky Quality Meter) module for calculating sky background brightness.

This module provides:
- SQM: Main calculator for sky quality measurements using aperture photometry
- NoiseFloorEstimator: Adaptive noise floor estimation with camera calibration
- CameraProfile: Dataclass containing camera hardware and noise characteristics
- get_camera_profile: Lookup camera profile by type (e.g., "imx296", "hq")
- detect_camera_type: Map hardware IDs to profile names
"""

from .sqm import SQM
from .noise_floor import NoiseFloorEstimator
from .camera_profiles import get_camera_profile, detect_camera_type, CameraProfile

__all__ = [
    "SQM",
    "NoiseFloorEstimator",
    "CameraProfile",
    "get_camera_profile",
    "detect_camera_type",
]
