"""
Camera profiles for Pi camera hardware.

These profiles contain all camera-specific configuration including hardware
settings and noise parameters. Values are based on datasheets, measurements,
and initial estimates. Noise parameters should be refined through real-world
dark frame measurements for improved accuracy.
"""

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class CameraProfile:
    """
    Complete camera configuration and noise characteristics.

    Hardware settings (format, raw_size, gains) are camera-specific constants.
    Noise parameters (read_noise, dark_current, bias_offset) are based on
    datasheets and estimates - should be refined with real-world measurements.
    """

    # Hardware configuration
    # Picamera2 raw format string (e.g., "R10", "SRGGB12")
    format: str

    # Raw sensor size (width, height) in pixels
    raw_size: Tuple[int, int]

    # Analog gain setting (sensor-specific maximum or optimal value)
    analog_gain: float

    # Digital gain multiplier applied after sensor readout
    digital_gain: float = 1.0

    # Bit depth of the sensor
    bit_depth: int = 10

    # Pedestal/bias offset in ADU
    # The "zero point" added to prevent negative values
    bias_offset: float = 0.0

    # Image cropping and orientation
    # Crop amount (top, bottom) in pixels
    crop_y: Tuple[int, int] = (0, 0)

    # Crop amount (left, right) in pixels
    crop_x: Tuple[int, int] = (0, 0)

    # Number of 90-degree counter-clockwise rotations (for np.rot90)
    rotation_90: int = 0

    # Noise characteristics for SQM calculations
    # Read noise in ADU (from 0-second exposures at 20°C)
    # Represents the fundamental noise floor of the sensor electronics
    read_noise_adu: float = 0.0

    # Dark current rate in ADU/second (at 20°C)
    # Thermal electrons generated even without light
    dark_current_rate: float = 0.0

    # Thermal coefficient in (fractional increase per °C)
    # Dark current approximately doubles every 8-10°C
    # NOTE: We don't have sensor temperature (only CPU temp), so this is
    # for reference only. Real devices will see ambient temperature variation.
    thermal_coeff: float = 0.0

    # Typical dark sky background for validation (mag/arcsec²)
    # Used to sanity-check SQM estimates
    typical_sky_background: float = 21.0

    def crop_and_rotate(self, raw_array):
        """
        Apply camera-specific cropping and rotation to raw array.

        Args:
            raw_array: Raw sensor data (numpy array)

        Returns:
            Cropped and rotated array
        """
        import numpy as np

        # Apply cropping
        crop_top, crop_bottom = self.crop_y
        crop_left, crop_right = self.crop_x

        if crop_top == 0 and crop_bottom == 0:
            y_slice = slice(None)  # All rows
        else:
            y_slice = slice(crop_top, -crop_bottom if crop_bottom > 0 else None)

        if crop_left == 0 and crop_right == 0:
            x_slice = slice(None)  # All columns
        else:
            x_slice = slice(crop_left, -crop_right if crop_right > 0 else None)

        cropped = raw_array[y_slice, x_slice]

        # Apply rotation if needed
        if self.rotation_90 != 0:
            cropped = np.rot90(cropped, self.rotation_90)

        return cropped

    def __repr__(self) -> str:
        return (
            f"CameraProfile("
            f"{self.format}, {self.raw_size}, "
            f"gain={self.analog_gain:.0f}, dgain={self.digital_gain:.1f}, "
            f"{self.bit_depth}bit, offset={self.bias_offset:.1f})"
        )


# Initial camera profiles based on datasheets and estimates
# Hardware settings are camera-specific constants
# Noise parameters should be refined with real-world dark frame measurements
# Dark current values assume ~20-25°C ambient temperature
# Note: Conversion from electrons to ADU varies by bit depth and gain settings
CAMERA_PROFILES: Dict[str, CameraProfile] = {
    "imx296": CameraProfile(
        # Hardware configuration
        format="R10",  # 10-bit raw format
        raw_size=(
            1456,
            1088,
        ),  # Avoid auto 728x544 mode that blacks out at high exposure
        analog_gain=15.0,  # Maximum analog gain for this sensor
        digital_gain=1.0,  # TODO: find optimum value
        bit_depth=10,
        bias_offset=32.0,  # Measured from actual dark frames
        # Image cropping and orientation
        crop_y=(0, 0),  # No vertical crop
        crop_x=(184, 184),  # Crop to square from horizontal rectangle
        rotation_90=2,  # 180-degree rotation (sensor orientation differs)
        # Noise characteristics
        read_noise_adu=2.5,  # Datasheet: 2.2e⁻ typical → ~2.5 ADU @ 10-bit
        dark_current_rate=8.0,  # Datasheet: 3.2 e⁻/p/s @ 25°C → ~8 ADU/s @ 10-bit
        thermal_coeff=0.08,  # Typical for CMOS sensors (no sensor temp available)
        typical_sky_background=21.0,
    ),
    "imx462": CameraProfile(
        # Hardware configuration
        format="SRGGB12",  # 12-bit Bayer format
        raw_size=(1920, 1080),
        analog_gain=30.0,
        digital_gain=1.0,  # TODO: find optimum value
        bit_depth=12,
        bias_offset=50.0,  # TODO: measure with dark frames
        # Image cropping and orientation
        crop_y=(50, 50),  # Crop vertical edges
        crop_x=(470, 470),  # Crop horizontal edges to square
        rotation_90=0,  # No rotation needed
        # Noise characteristics
        read_noise_adu=3.2,  # Estimated (STARVIS, similar to IMX290)
        dark_current_rate=0.05,  # Estimated - needs measurement
        thermal_coeff=0.10,  # Typical for CMOS sensors (no sensor temp available)
        typical_sky_background=21.0,
    ),
    "imx290": CameraProfile(
        # Hardware configuration (same as imx462 - driver compatibility)
        format="SRGGB12",  # 12-bit Bayer format
        raw_size=(1920, 1080),
        analog_gain=30.0,
        digital_gain=1.0,  # TODO: find optimum value
        bit_depth=12,
        bias_offset=50.0,  # TODO: measure with dark frames
        # Image cropping and orientation (same as imx462)
        crop_y=(50, 50),  # Crop vertical edges
        crop_x=(470, 470),  # Crop horizontal edges to square
        rotation_90=0,  # No rotation needed
        # Noise characteristics
        read_noise_adu=3.0,  # Measured: 3.3-3.5e⁻ @ 0dB → ~3 ADU @ 12-bit
        dark_current_rate=0.04,  # Estimated - needs measurement
        thermal_coeff=0.10,  # Typical for CMOS sensors (no sensor temp available)
        typical_sky_background=21.0,
    ),
    "hq": CameraProfile(
        # Hardware configuration
        format="SRGGB12",  # 12-bit Bayer format
        raw_size=(2028, 1520),  # Smaller size auto-selects sensor binning
        analog_gain=22.0,  # Cedar uses this value
        digital_gain=13.0,  # Initial tests show higher values don't help much
        bit_depth=12,
        bias_offset=256.0,  # Measured with lens cap on
        # Image cropping and orientation
        crop_y=(0, 0),  # No vertical crop
        crop_x=(256, 256),  # Crop to square from horizontal rectangle
        rotation_90=0,  # No rotation needed
        # Noise characteristics
        read_noise_adu=4.0,  # Estimated (IMX477, no published specs)
        dark_current_rate=0.02,  # Estimated - needs measurement
        thermal_coeff=0.09,  # Typical for CMOS sensors (no sensor temp available)
        typical_sky_background=21.0,
    ),
    # Processed image profiles (8-bit images after camera.capture() processing)
    # These have been rescaled to 0-255 but still have residual offset from:
    # - Imperfect bias subtraction in camera.capture()
    # - Quantization floor after 8-bit conversion
    # - Read noise floor
    # Measured from actual processed images: darkest pixels ~9-12 ADU
    # Use conservative offset to avoid over-subtraction
    # Note: Hardware fields not used for processed images (already 8-bit)
    "imx296_processed": CameraProfile(
        format="L",  # 8-bit grayscale (not used)
        raw_size=(512, 512),  # Already processed size (not used)
        analog_gain=1.0,  # Not applicable to processed images
        digital_gain=1.0,  # Already applied during processing
        bit_depth=8,
        bias_offset=6.0,  # Calibrated against reference SQM meter
        read_noise_adu=1.5,  # Quantization + residual noise in 8-bit
        dark_current_rate=0.0,  # Negligible after processing
        thermal_coeff=0.0,
        typical_sky_background=21.0,
    ),
    "imx462_processed": CameraProfile(
        format="L",
        raw_size=(512, 512),
        analog_gain=1.0,
        digital_gain=1.0,
        bit_depth=8,
        bias_offset=8.0,
        read_noise_adu=1.5,
        dark_current_rate=0.0,
        thermal_coeff=0.0,
        typical_sky_background=21.0,
    ),
    "imx290_processed": CameraProfile(
        format="L",
        raw_size=(512, 512),
        analog_gain=1.0,
        digital_gain=1.0,
        bit_depth=8,
        bias_offset=8.0,
        read_noise_adu=1.5,
        dark_current_rate=0.0,
        thermal_coeff=0.0,
        typical_sky_background=21.0,
    ),
    "hq_processed": CameraProfile(
        format="L",
        raw_size=(512, 512),
        analog_gain=1.0,
        digital_gain=1.0,
        bit_depth=8,
        bias_offset=8.0,
        read_noise_adu=1.5,
        dark_current_rate=0.0,
        thermal_coeff=0.0,
        typical_sky_background=21.0,
    ),
}


def detect_camera_type(hardware_id: str) -> str:
    """
    Detect camera profile name from hardware ID string.

    Args:
        hardware_id: Camera hardware identifier (e.g., from Picamera2.camera.id)

    Returns:
        Camera profile name (e.g., "imx296", "hq")

    Raises:
        ValueError: If hardware ID is not recognized

    Example:
        >>> detect_camera_type("imx296")
        'imx296'
        >>> detect_camera_type("imx477")
        'hq'
    """
    # Mapping of hardware ID substrings to profile names
    hardware_mappings = {
        "imx296": "imx296",
        "imx290": "imx462",  # IMX290 uses IMX462 profile (driver compatibility)
        "imx477": "hq",
    }

    # Check each known hardware ID substring
    for hw_substring, profile_name in hardware_mappings.items():
        if hw_substring in hardware_id.lower():
            return profile_name

    # No match found
    raise ValueError(
        f"Unknown camera hardware ID: {hardware_id}. "
        f"Supported: {list(hardware_mappings.keys())}"
    )


def get_camera_profile(camera_type: str) -> CameraProfile:
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
