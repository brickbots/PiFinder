"""
Camera profiles for Pi camera hardware.

These profiles contain all camera-specific configuration including hardware
settings and noise parameters. Values are based on datasheets, measurements,
and initial estimates. Noise parameters should be refined through real-world
dark frame measurements for improved accuracy.
"""

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np


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

    # SQM colour transformation coefficient T for mag_eff = V - T*(B-V).
    # The catalog magnitude is Johnson V, but the flux is measured in the
    # sensor's own passband. On a sensor run without an IR-cut filter the near-IR
    # leak over-fluxes red stars, so T is positive. Measured per sensor model:
    # imx462/imx290 bare color ~0.8; hq (factory IR-cut) ~0.0. 0.0 = no correction.
    color_coefficient: float = 0.0

    # Sky-passband offset (mag), added to the final SQM. The colour term
    # matches the *stars* to the sensor passband, but the *sky* is then also
    # measured in that passband: a bare sensor sees NIR sky emission (airglow,
    # LED/sodium light pollution beyond 700nm) that a V-band SQM meter does
    # not, so its sky reads genuinely brighter. This constant converts the
    # sensor-band sky brightness back to the meter's V-band scale.
    #
    # NOT a pure sensor constant: it is (sensor passband, fixed) x (sky
    # spectrum, environmental). The values below are calibrated under an
    # LP-dominated suburban sky (Ghent), where the city's stable spectrum
    # makes the offset constant to ~0.05 mag across nights. Under an
    # airglow-dominated dark sky the NIR fraction is different and variable,
    # so expect a different (likely larger) value there and real night-to-
    # night wander. Refine per sky regime with side-by-side reference-meter
    # or paired IR-cut-camera sessions.
    sqm_band_offset: float = 0.0

    def crop_and_rotate(self, raw_array):
        """
        Apply camera-specific cropping and rotation to raw array.

        Args:
            raw_array: Raw sensor data (numpy array)

        Returns:
            Cropped and rotated array
        """
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
        # Sony-standard black level (240 @ 12-bit -> 60 @ 10-bit); confirmed by
        # the 2025-10-31 on-sky sweep intercept (60.3). The old 32.0 was a
        # mis-measurement.
        bias_offset=60.0,
        # Image cropping and orientation
        crop_y=(0, 0),  # No vertical crop
        crop_x=(184, 184),  # Crop to square from horizontal rectangle
        rotation_90=2,  # 180-degree rotation (sensor orientation differs)
        # Noise characteristics
        read_noise_adu=2.5,  # Datasheet: 2.2e⁻ typical → ~2.5 ADU @ 10-bit
        dark_current_rate=8.0,  # Datasheet: 3.2 e⁻/p/s @ 25°C → ~8 ADU/s @ 10-bit
        thermal_coeff=0.08,  # Typical for CMOS sensors (no sensor temp available)
        typical_sky_background=21.0,
        # Measured on-sky (2025-10-31 sweep, 460 stars): +0.21. Small because
        # the Pregius mono QE falls through the NIR, unlike the STARVIS colour
        # sensors' NIR-heavy green channel.
        color_coefficient=0.21,
        # Refit for the growth-curve pipeline from the same single moonlit
        # 2025-10-31 sweep vs its 17.8-17.9 hand-held reference (+/-0.2).
        # Near zero is physically consistent: the Pregius mono passband is
        # the closest of the three sensors to the meter's.
        sqm_band_offset=-0.10,
    ),
    "imx462": CameraProfile(
        # Hardware configuration
        format="SRGGB12",  # 12-bit Bayer format
        raw_size=(1920, 1080),
        analog_gain=30.0,
        digital_gain=1.0,  # TODO: find optimum value
        bit_depth=12,
        bias_offset=238.0,  # Measured: dark-frame CAL 238.0 + on-sky sweep intercept 238.6 (raw green, gain 30)
        # Image cropping and orientation
        crop_y=(50, 50),  # Crop vertical edges
        crop_x=(470, 470),  # Crop horizontal edges to square
        rotation_90=0,  # No rotation needed
        # Noise characteristics
        read_noise_adu=3.2,  # Estimated (STARVIS, similar to IMX290)
        dark_current_rate=0.05,  # Estimated - needs measurement
        thermal_coeff=0.10,  # Typical for CMOS sensors (no sensor temp available)
        typical_sky_background=21.0,
        # Measured on-sky: +0.79 ± 0.04 (bare color sensor, NIR leak over-fluxes
        # red stars). Cross-checked against HQ w/ IR-cut (~0.0) and synthetic
        # photometry. See docs/adr for the SQM colour-term decision.
        color_coefficient=0.8,
        # Bare sensor sees NIR sky emission a V-band meter doesn't. Calibrated
        # from 6 referenced clear-night sweeps (2026-07-11..16) with the
        # growth-curve aperture correction (which measures f=1.0 on this
        # optics): residuals +/-0.06. Coupled to the estimator and the
        # centroid-excluded annulus background -- recalibrate together.
        sqm_band_offset=0.61,
    ),
    "imx290": CameraProfile(
        # Hardware configuration (same as imx462 - driver compatibility)
        format="SRGGB12",  # 12-bit Bayer format
        raw_size=(1920, 1080),
        analog_gain=30.0,
        digital_gain=1.0,  # TODO: find optimum value
        bit_depth=12,
        bias_offset=238.0,  # Measured: dark-frame CAL 238.0 + on-sky sweep intercept 238.6 (raw green, gain 30)
        # Image cropping and orientation (same as imx462)
        crop_y=(50, 50),  # Crop vertical edges
        crop_x=(470, 470),  # Crop horizontal edges to square
        rotation_90=0,  # No rotation needed
        # Noise characteristics
        read_noise_adu=3.0,  # Measured: 3.3-3.5e⁻ @ 0dB → ~3 ADU @ 12-bit
        dark_current_rate=0.04,  # Estimated - needs measurement
        thermal_coeff=0.10,  # Typical for CMOS sensors (no sensor temp available)
        typical_sky_background=21.0,
        # Same sensor family/optics as imx462 (driver-compatible), same NIR leak.
        color_coefficient=0.8,
        sqm_band_offset=0.61,  # mirror of imx462 (same sensor family, no sweeps yet)
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
        # Measured on-sky: -0.05 ± 0.01 -> effectively 0. HQ ships with a factory
        # IR-cut filter, so no NIR leak and the green passband ~ Johnson V.
        color_coefficient=0.0,
        # Calibrated from 3 independent clear-night reference readings
        # (2025-11-16, 2025-11-18, 2026-07-16) with the growth-curve aperture
        # correction (this optics shows mild, focus-dependent wings,
        # f 0.87-1.0, measured per session). Residuals within +/-0.2; the
        # shared 2025-11-16 reading remains the outlier. Non-zero despite the
        # IR-cut: the residual absorbs passband + optics differences vs the
        # meter. Coupled to the estimator -- recalibrate together.
        sqm_band_offset=0.60,
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
        "imx462": "imx462",  # Sensor self-reports as imx462
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
