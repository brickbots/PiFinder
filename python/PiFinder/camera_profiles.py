"""
Camera profiles for Pi camera hardware.

These profiles contain all camera-specific configuration including hardware
settings and noise parameters. Values are based on datasheets, measurements,
and initial estimates. Noise parameters should be refined through real-world
dark frame measurements for improved accuracy.

A profile describes the *sensor* half of the optical train only. Nothing here
knows what lens is fitted, so nothing here is a field of view: pair a profile
with a :class:`~PiFinder.optics.Lens` to derive one. See
``docs/ax/camera/CONTEXT.md`` (Optics) and ``docs/adr/0027``.
"""

from dataclasses import dataclass, replace
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

    # Physical pixel spacing in micrometres, at the readout mode this profile
    # configures. Binned modes state the *binned* pitch (the HQ's 2028x1520
    # mode is 2x2 binned, so 3.10 rather than the IMX477's native 1.55).
    # With the crop width this gives the imaged extent in mm, which with a
    # lens's effective focal length gives the field of view.
    pixel_pitch_um: float = 0.0

    # The lens to *assume* when the config states none -- see "assumed lens"
    # in docs/ax/camera/CONTEXT.md. Existing installs predate the lens setting
    # entirely, so this is what makes them resolve correctly with no
    # migration; it must stay accurate to what shipped, not to what is
    # currently preferred. It is only the assumption, not the whole story:
    # more than one lens has shipped on some sensors, and which of them is in
    # the box is exactly what an assumption cannot know.
    default_lens_key: str = ""

    # Every lens this sensor has shipped with. The assumed-lens FOV gate spans
    # all of them, so this is the set of lenses a unit with no stated lens can
    # still solve on, and the set self-heal is allowed to identify from.
    # default_lens_key must be one of these (asserted in test_optics.py).
    shipped_lens_keys: Tuple[str, ...] = ()

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

    # Clear-sky exposure-normalized zero point (mzero - 2.5*log10(exposure),
    # airmass- and aperture-normalized) measured for this sensor. Seeds the
    # cloud estimator's baseline so the transmission monitor works from the
    # first frame, before a session has conditioned its own baseline (the
    # boot-under-cloud case). 0.0 = unknown (estimator waits for conditioning).
    clear_zero_point: float = 0.0

    # Typical clear-sky SQM (mag/arcsec²) at this device's usual site. Seeds
    # the sky-excess guard: cloud brightens the sky (SQM drops below this),
    # dew/optics do not. 0.0 = unknown (guard waits for a learned level).
    clear_sky_brightness: float = 0.0

    # Fixed conversion from exposure-normalized diffuse-sky ADU/arcsec² to the
    # SQM-L-equivalent scale. Unlike the live stellar zero point, this remains
    # available through cloud or a failed solve. It includes the passband offset.
    radiometric_zero_point: float = 0.0

    # Sky-colour dependence of the radiometric zero point, in mag per unit of
    # sky R/G. The radiometer measures sky in the sensor's passband while the
    # reference meter measures V, and the conversion between them depends on
    # the sky's spectrum: light pollution is sodium/LED and green-weighted,
    # airglow is grey and NIR-rich. On a bare sensor that difference is worth
    # ~0.8 mag between an LP site and a dark one, so a single constant is
    # wrong at one end or the other. Measured per sensor; 0.0 disables the
    # correction and keeps a plain constant (mono sensors have no colour, and
    # an IR-cut sensor has almost no NIR leak to correct).
    # Derivation, evidence and caveats: docs/adr/0026. Re-derive with
    # scripts/evaluate_radiometer_archive.py rather than by hand.
    radiometric_colour_slope: float = 0.0

    # R/G at which radiometric_zero_point is exactly right, so a frame with no
    # colour information falls back to a sensible constant rather than to the
    # fit's intercept.
    radiometric_colour_pivot: float = 0.0

    # R/G range the slope was calibrated over. Values outside are clamped
    # rather than extrapolated.
    radiometric_colour_range: Tuple[float, float] = (0.0, 10.0)

    # Catalog reference band for the photometric zero point:
    # "gaia_g"  -- Gaia G with a BP-RP trim (bare sensors: G's passband is
    #              nearly the sensor's own; measured 24-29% less star scatter)
    # "hip_v"   -- Hipparcos/Johnson V with the linear B-V term (IR-cut
    #              sensors, whose passband ~ V)
    reference_band: str = "hip_v"

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

    @property
    def crop_size(self) -> Tuple[int, int]:
        """(width, height) in pixels of what :meth:`crop_and_rotate` returns.

        This is the extent every derived angle is measured across -- the raw
        sensor is wider than what PiFinder actually images.
        """
        width = self.raw_size[0] - sum(self.crop_x)
        height = self.raw_size[1] - sum(self.crop_y)
        if self.rotation_90 % 2:
            width, height = height, width
        return (width, height)

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

    def is_full_sensor(self, raw_array) -> bool:
        """True when an array covers the whole sensor rather than the crop.

        Sweeps archive the full sensor; photometry works on the crop. Both
        eras of archive exist on disk, so anything replaying them has to tell
        them apart. The sizes can never collide: the crop is strictly smaller
        on at least one axis for every profile.
        """
        height, width = raw_array.shape[:2]
        return (width, height) == self.raw_size

    def ensure_cropped(self, raw_array):
        """Reduce an archived frame to what production photometry would see.

        A full-sensor frame goes through the ordinary :meth:`crop_and_rotate`,
        so the result matches the live pipeline by construction rather than by
        a parallel reimplementation. An already-cropped frame is returned
        untouched.
        """
        if self.is_full_sensor(raw_array):
            return self.crop_and_rotate(raw_array)
        return raw_array

    def __repr__(self) -> str:
        return (
            f"CameraProfile("
            f"{self.format}, {self.raw_size}, "
            f"gain={self.analog_gain:.0f}, dgain={self.digital_gain:.1f}, "
            f"{self.bit_depth}bit, offset={self.bias_offset:.1f})"
        )


# Initial camera-profile templates based on datasheets and estimates. Callers
# receive copies so loading or refining one calibration cannot mutate every
# other calculator in the process.
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
        pixel_pitch_um=3.45,  # Sony Pregius S IMX296 datasheet
        default_lens_key="16mm",
        shipped_lens_keys=("16mm", "12mm"),
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
        # From the 2025-10-31 sweep (normalized zero point 14.23); clear-sky
        # SQM at the moonlit reference sky ~17.9.
        clear_zero_point=14.23,
        clear_sky_brightness=17.9,
        radiometric_zero_point=14.07,
        reference_band="gaia_g",
        # BP-RP trim on the Gaia G reference, fit on the 2025-10-31 sweep
        # (54 frames): scatter 0.108 -> 0.077, mag-slope +0.13 -> +0.01.
        color_coefficient=-0.20,
        # Refit for the growth-curve pipeline from the same single moonlit
        # 2025-10-31 sweep vs its 17.8-17.9 hand-held reference (+/-0.2).
        # Near zero is physically consistent: the Pregius mono passband is
        # the closest of the three sensors to the meter's.
        # Re-derived 2026-07-31 from Rich's four referenced imx296 sweeps
        # (34 frames): per-sweep median stellar SQM against reference_sqm gives
        # a median residual of +0.199 mag, tight across all four (+0.13..+0.22).
        # The method reproduces imx462's shipped 0.53 to within 0.02, so it is
        # not a systematic of the replay. See the PR for the full derivation.
        sqm_band_offset=-0.02,
    ),
    "imx462": CameraProfile(
        # Hardware configuration
        format="SRGGB12",  # 12-bit Bayer format
        raw_size=(1920, 1080),
        analog_gain=30.0,
        digital_gain=1.0,  # TODO: find optimum value
        bit_depth=12,
        pixel_pitch_um=2.90,  # Sony STARVIS IMX462 datasheet
        default_lens_key="16mm",
        # Some rev4 units shipped with the 12mm and no stated lens, which is
        # the failure ADR 0029 exists to fix. Both belong here.
        shipped_lens_keys=("16mm", "12mm"),
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
        # Six clear 2026-07 sweeps: normalized zero point 14.81 (stable +/-0.05
        # night to night); clear-sky SQM ~18.5 at the Ghent test site.
        clear_zero_point=14.81,
        clear_sky_brightness=18.5,
        radiometric_zero_point=15.159,
        # Re-derived 2026-07-31 over 23 referenced sweeps spanning 17.5-20.9
        # mag skies. A single constant left the published value ~0.10 mag dark
        # at the LP site and ~0.85 mag bright at a dark one; keying the zero
        # point to measured sky colour collapses both regimes into one model
        # (residual sd 0.337 -> 0.079). Leave-one-night-out CV: MAE 0.247 ->
        # 0.108, and holding out the only dark night -- so the model never saw
        # that regime -- 0.944 -> 0.312, i.e. it extrapolates rather than
        # interpolates. The same fit on the IR-cut HQ is rejected by CV, which
        # is the expected result for a NIR-leak term and the reason to believe
        # this one.
        radiometric_colour_slope=5.544,
        radiometric_colour_pivot=0.85,
        radiometric_colour_range=(0.83, 1.04),
        reference_band="gaia_g",
        # BP-RP trim on the Gaia G reference, fit on 6 clear sweeps
        # (92 frames): scatter 0.224 -> 0.171, mag-slope +0.10 -> +0.06.
        color_coefficient=0.15,
        # Bare sensor sees NIR sky emission a V-band meter doesn't. Calibrated
        # from 6 referenced clear-night sweeps (2026-07-11..16) with the
        # growth-curve aperture correction (which measures f=1.0 on this
        # optics): residuals +/-0.06. Coupled to the estimator and the
        # centroid-excluded annulus background -- recalibrate together.
        sqm_band_offset=0.53,
    ),
    "imx290": CameraProfile(
        # Hardware configuration (same as imx462 - driver compatibility)
        format="SRGGB12",  # 12-bit Bayer format
        raw_size=(1920, 1080),
        analog_gain=30.0,
        digital_gain=1.0,  # TODO: find optimum value
        bit_depth=12,
        pixel_pitch_um=2.90,  # Same sensor family as imx462
        default_lens_key="16mm",
        shipped_lens_keys=("16mm", "12mm"),
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
        # Same sensor family/optics as imx462 (driver-compatible): mirror seeds.
        clear_zero_point=14.81,
        clear_sky_brightness=18.5,
        radiometric_zero_point=15.159,
        # Re-derived 2026-07-31 over 23 referenced sweeps spanning 17.5-20.9
        # mag skies. A single constant left the published value ~0.10 mag dark
        # at the LP site and ~0.85 mag bright at a dark one; keying the zero
        # point to measured sky colour collapses both regimes into one model
        # (residual sd 0.337 -> 0.079). Leave-one-night-out CV: MAE 0.247 ->
        # 0.108, and holding out the only dark night -- so the model never saw
        # that regime -- 0.944 -> 0.312, i.e. it extrapolates rather than
        # interpolates. The same fit on the IR-cut HQ is rejected by CV, which
        # is the expected result for a NIR-leak term and the reason to believe
        # this one.
        radiometric_colour_slope=5.544,
        radiometric_colour_pivot=0.85,
        radiometric_colour_range=(0.83, 1.04),
        # Same sensor family/optics as imx462 (driver-compatible), same NIR leak.
        reference_band="gaia_g",
        color_coefficient=0.15,  # mirror of imx462 (same sensor family)
        sqm_band_offset=0.53,  # mirror of imx462 (same sensor family, no sweeps yet)
    ),
    "hq": CameraProfile(
        # Hardware configuration
        format="SRGGB12",  # 12-bit Bayer format
        raw_size=(2028, 1520),  # Smaller size auto-selects sensor binning
        analog_gain=22.0,  # Cedar uses this value
        digital_gain=13.0,  # Initial tests show higher values don't help much
        bit_depth=12,
        # IMX477's native pitch is 1.55; the 2028x1520 mode above 2x2-bins it.
        pixel_pitch_um=3.10,
        # The HQ build shipped with the longer lens, so it is the only profile
        # whose no-config default is not the 16mm. It is also the only one
        # that ever shipped a single lens, so its assumed gate is identical to
        # its stated one -- nothing about the HQ widens under ADR 0029.
        default_lens_key="25mm",
        shipped_lens_keys=("25mm",),
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
        # Archive HQ sweeps: normalized zero point ~14.19 (wanders +/-0.5 with
        # focus/dew, so the session baseline leads and this only seeds boot);
        # clear-sky SQM ~18.5 at the reference sites.
        clear_zero_point=14.19,
        clear_sky_brightness=18.5,
        # Re-derived 2026-07-31 over 11 referenced sweeps: the shipped 14.79
        # read bright on 10 of 11 (median +0.181). Stays a constant -- the
        # factory IR-cut leaves almost no NIR leak, its colour slope measures
        # 20x smaller than the imx462's, and leave-one-night-out CV rejects
        # the colour term outright (MAE 0.182 constant vs 0.234 with colour).
        radiometric_zero_point=14.971,
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
        # Re-derived 2026-07-31 over 9 referenced hq sweeps: the shipped 0.60
        # left every sweep reading brighter than the meter (residuals +0.01 to
        # +0.68, median +0.386); 0.99 zeroes that median.
        #
        # Note this fights the physics. The offset is meant to be a passband
        # term, and the HQ's factory IR-cut means it should be near zero -- but
        # zero puts the stellar SQM ~1 mag bright. So roughly a magnitude of
        # the HQ stellar chain is unaccounted for and this constant is
        # absorbing it. The value is fitted, not physical; if the real error is
        # found, refit rather than assuming this number transfers.
        #
        # Sweep-to-sweep scatter is 0.67 mag (dew/throughput), so treat this as
        # 0.99 +/- 0.2 rather than a precise figure.
        sqm_band_offset=0.99,
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
    return replace(CAMERA_PROFILES[camera_type])
