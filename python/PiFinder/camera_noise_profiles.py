"""
Camera noise profiles for adaptive noise floor estimation.

These profiles contain pre-characterized noise parameters for each camera model,
measured under controlled conditions (dark frames, temperature-controlled environment).
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class CameraNoiseProfile:
    """
    Noise characteristics for a camera model.

    These values are measured once in a lab setting and serve as the baseline
    for adaptive noise floor estimation in the field.
    """

    # Read noise in ADU (from 0-second exposures at 20°C)
    # Represents the fundamental noise floor of the sensor electronics
    read_noise_adu: float

    # Dark current rate in ADU/second (at 20°C)
    # Thermal electrons generated even without light
    dark_current_rate: float

    # Thermal coefficient in (fractional increase per °C)
    # Dark current approximately doubles every 8-10°C
    # NOTE: We don't have sensor temperature (only CPU temp), so this is
    # for reference only. Real devices will see ambient temperature variation.
    thermal_coeff: float = 0.0

    # Pedestal/bias offset in ADU
    # The "zero point" added to prevent negative values
    bias_offset: float = 0.0

    # Bit depth of the sensor
    bit_depth: int = 10

    # Typical dark sky background for validation (mag/arcsec²)
    # Used to sanity-check estimates
    typical_sky_background: float = 21.0

    def __repr__(self) -> str:
        return (
            f"CameraNoiseProfile("
            f"read_noise={self.read_noise_adu:.2f} ADU, "
            f"dark_current={self.dark_current_rate:.3f} ADU/s, "
            f"bias={self.bias_offset:.1f} ADU)"
        )


# Pre-characterized profiles (from lab measurements)
# TODO: These need to be measured for actual devices
CAMERA_PROFILES: Dict[str, CameraNoiseProfile] = {
    "imx296": CameraNoiseProfile(
        read_noise_adu=2.5,      # Low read noise (global shutter advantage)
        dark_current_rate=0.01,  # ADU/sec @ ~20°C ambient - very low
        thermal_coeff=0.08,      # Reference only (no sensor temp available)
        bias_offset=32.0,        # Measured from dark frames
        bit_depth=10,
        typical_sky_background=21.0,
    ),
    "imx462": CameraNoiseProfile(
        read_noise_adu=3.2,      # Higher read noise (rolling shutter)
        dark_current_rate=0.05,  # ADU/sec @ ~20°C ambient - moderate
        thermal_coeff=0.10,      # Reference only (no sensor temp available)
        bias_offset=50.0,        # TODO: measure with measure_imx462_offset.py
        bit_depth=12,
        typical_sky_background=21.0,
    ),
    "imx290": CameraNoiseProfile(
        read_noise_adu=3.0,      # Similar to IMX462
        dark_current_rate=0.04,  # ADU/sec @ ~20°C ambient
        thermal_coeff=0.10,      # Reference only (no sensor temp available)
        bias_offset=50.0,        # TODO: measure
        bit_depth=12,
        typical_sky_background=21.0,
    ),
    "hq": CameraNoiseProfile(
        read_noise_adu=4.0,      # HQ camera (IMX477)
        dark_current_rate=0.02,  # ADU/sec @ ~20°C ambient
        thermal_coeff=0.09,      # Reference only (no sensor temp available)
        bias_offset=256.0,       # From camera_pi.py
        bit_depth=12,
        typical_sky_background=21.0,
    ),
}


def get_camera_profile(camera_type: str) -> CameraNoiseProfile:
    """
    Get the noise profile for a camera type.

    Args:
        camera_type: Camera model identifier (imx296, imx462, imx290, hq)

    Returns:
        CameraNoiseProfile for the camera

    Raises:
        ValueError: If camera type is not recognized
    """
    if camera_type not in CAMERA_PROFILES:
        raise ValueError(
            f"Unknown camera type: {camera_type}. "
            f"Available: {list(CAMERA_PROFILES.keys())}"
        )
    return CAMERA_PROFILES[camera_type]
