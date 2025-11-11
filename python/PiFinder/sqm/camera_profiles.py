"""
Camera noise profiles for adaptive noise floor estimation.

These profiles contain noise parameters for each camera model based on datasheets
and initial estimates. Values should be refined through real-world measurements
with actual hardware and observing conditions.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class CameraNoiseProfile:
    """
    Noise characteristics for a camera model.

    Values are based on datasheets and initial estimates. Should be refined
    with real-world dark frame measurements for improved accuracy.
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


# Initial camera profiles based on datasheets and estimates
# These values should be refined with real-world dark frame measurements
# Dark current values assume ~20-25°C ambient temperature
# Note: Conversion from electrons to ADU varies by bit depth and gain settings
CAMERA_PROFILES: Dict[str, CameraNoiseProfile] = {
    "imx296": CameraNoiseProfile(
        read_noise_adu=2.5,  # Datasheet: 2.2e⁻ typical → ~2.5 ADU @ 10-bit
        dark_current_rate=8.0,  # Datasheet: 3.2 e⁻/p/s @ 25°C → ~8 ADU/s @ 10-bit
        thermal_coeff=0.08,  # Typical for CMOS sensors (no sensor temp available)
        bias_offset=32.0,  # Measured from actual dark frames
        bit_depth=10,
        typical_sky_background=21.0,
    ),
    "imx462": CameraNoiseProfile(
        read_noise_adu=3.2,  # Estimated (STARVIS, similar to IMX290)
        dark_current_rate=0.05,  # Estimated - needs measurement
        thermal_coeff=0.10,  # Reference only (no sensor temp available)
        bias_offset=50.0,  # TODO: measure with dark frames
        bit_depth=12,
        typical_sky_background=21.0,
    ),
    "imx290": CameraNoiseProfile(
        read_noise_adu=3.0,  # Measured: 3.3-3.5e⁻ @ 0dB → ~3 ADU @ 12-bit
        dark_current_rate=0.04,  # Estimated - needs measurement
        thermal_coeff=0.10,  # Reference only (no sensor temp available)
        bias_offset=50.0,  # TODO: measure with dark frames
        bit_depth=12,
        typical_sky_background=21.0,
    ),
    "hq": CameraNoiseProfile(
        read_noise_adu=4.0,  # Estimated (IMX477, no published specs)
        dark_current_rate=0.02,  # Estimated - needs measurement
        thermal_coeff=0.09,  # Reference only (no sensor temp available)
        bias_offset=256.0,  # From camera_pi.py
        bit_depth=12,
        typical_sky_background=21.0,
    ),
    # Processed image profiles (8-bit images after camera.capture() processing)
    # These have been rescaled to 0-255 but still have residual offset from:
    # - Imperfect bias subtraction in camera.capture()
    # - Quantization floor after 8-bit conversion
    # - Read noise floor
    # Measured from actual processed images: darkest pixels ~9-12 ADU
    # Use conservative offset to avoid over-subtraction
    "imx296_processed": CameraNoiseProfile(
        read_noise_adu=1.5,  # Quantization + residual noise in 8-bit
        dark_current_rate=0.0,  # Negligible after processing
        thermal_coeff=0.0,
        bias_offset=8.0,  # Conservative - below typical dark pixels (9-12)
        bit_depth=8,
        typical_sky_background=21.0,
    ),
    "imx462_processed": CameraNoiseProfile(
        read_noise_adu=1.5,
        dark_current_rate=0.0,
        thermal_coeff=0.0,
        bias_offset=8.0,
        bit_depth=8,
        typical_sky_background=21.0,
    ),
    "imx290_processed": CameraNoiseProfile(
        read_noise_adu=1.5,
        dark_current_rate=0.0,
        thermal_coeff=0.0,
        bias_offset=8.0,
        bit_depth=8,
        typical_sky_background=21.0,
    ),
    "hq_processed": CameraNoiseProfile(
        read_noise_adu=1.5,
        dark_current_rate=0.0,
        thermal_coeff=0.0,
        bias_offset=8.0,
        bit_depth=8,
        typical_sky_background=21.0,
    ),
}


def get_camera_profile(camera_type: str) -> CameraNoiseProfile:
    """
    Get the noise profile for a camera type.

    Args:
        camera_type: Camera model identifier
            Raw sensors: imx296, imx462, imx290, hq
            Processed (8-bit): imx296_processed, imx462_processed, imx290_processed, hq_processed

    Returns:
        CameraNoiseProfile for the camera

    Raises:
        ValueError: If camera type is not recognized

    Note:
        Use "_processed" variants when working with 8-bit images that have already
        had bias offset subtracted and been scaled (e.g., from camera.capture()).
        Use raw variants only when working with unprocessed sensor data.
    """
    if camera_type not in CAMERA_PROFILES:
        raise ValueError(
            f"Unknown camera type: {camera_type}. "
            f"Available: {list(CAMERA_PROFILES.keys())}"
        )
    return CAMERA_PROFILES[camera_type]
