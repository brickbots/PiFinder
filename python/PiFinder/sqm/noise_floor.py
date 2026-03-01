"""
Adaptive noise floor estimation for SQM calculations.

This module estimates the camera noise floor without requiring lens caps or dark frames.
It uses a combination of:
1. Pre-characterized camera profiles (physics-based model)
2. Adaptive measurement from actual images (darkest pixels)
3. Optional zero-second exposures (periodic calibration)
"""

import numpy as np
from collections import deque
from typing import Tuple, Dict, Any
import time
import logging
import json
from pathlib import Path

from .camera_profiles import get_camera_profile

logger = logging.getLogger("PiFinder.NoiseFloorEstimator")


class NoiseFloorEstimator:
    """
    Estimates noise floor for SQM calculations using adaptive heuristics.

    This class combines:
    - Camera-specific physics models (read noise, dark current)
    - Empirical measurements from actual images (dark pixel percentiles)
    - Historical smoothing for stability
    - Optional zero-second calibration samples

    The goal is to estimate the "true zero" background level that should be
    subtracted before converting pixel values to sky brightness.
    """

    def __init__(
        self,
        camera_type: str,
        history_size: int = 20,
        enable_zero_sec_sampling: bool = True,
        zero_sec_interval: int = 300,  # 5 minutes
    ):
        """
        Initialize the noise floor estimator.

        Args:
            camera_type: Camera model (imx296, imx462, imx290, hq)
            history_size: Number of recent measurements to track for smoothing
            enable_zero_sec_sampling: Whether to request periodic 0-sec exposures
            zero_sec_interval: Seconds between zero-second calibration samples
        """
        self.camera_type = camera_type
        self.profile = get_camera_profile(camera_type)

        # Rolling history for adaptive estimation
        self.dark_pixel_history: deque = deque(maxlen=history_size)
        self.zero_sec_history: deque = deque(maxlen=10)

        # Zero-second sampling config
        self.enable_zero_sec = enable_zero_sec_sampling
        self.last_zero_sec_time = 0.0
        self.zero_sec_interval = zero_sec_interval

        # Statistics
        self.n_estimates = 0

        logger.info(
            f"Initialized NoiseFloorEstimator for {camera_type}: {self.profile}"
        )
        logger.info(
            "NOTE: No sensor temperature available (only CPU temp). "
            "Dark current estimate assumes ~20°C ambient temperature."
        )

        # Try to load saved calibration
        self.load_calibration()

    def estimate_noise_floor(
        self,
        image: np.ndarray,
        exposure_sec: float,
        percentile: float = 5.0,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Estimate noise floor from an actual sky image.

        Strategy:
        1. Measure darkest pixels as proxy for noise floor + dark sky background
        2. Estimate theoretical noise from camera physics (read noise + dark current)
        3. Take the minimum of the two (prevents overestimation when sky is bright)
        4. Smooth with historical measurements for stability

        Args:
            image: Image array (8-bit or 16-bit)
            exposure_sec: Exposure time in seconds
            percentile: Percentile of darkest pixels to use (lower = more conservative)

        Returns:
            Tuple of (noise_floor_adu, details_dict)
            - noise_floor_adu: Estimated noise floor in ADU units
            - details_dict: Diagnostic information for logging/debugging

        Note:
            Temperature correction is NOT applied because we only have CPU temperature,
            not sensor temperature. Dark current estimate assumes ~20°C ambient.
        """
        self.n_estimates += 1

        # 1. Measure darkest pixels as proxy
        # These should represent "empty sky" + noise floor
        dark_pixel_value = float(np.percentile(image, percentile))
        self.dark_pixel_history.append(dark_pixel_value)

        # 2. Estimate theoretical noise from physics
        temporal_noise = self._estimate_temporal_noise(exposure_sec)
        theoretical_noise_floor = self.profile.bias_offset + temporal_noise

        # 3. Smoothed measurement from history
        if len(self.dark_pixel_history) >= 5:
            # Use median for robustness against outliers
            dark_pixel_smoothed = float(np.median(list(self.dark_pixel_history)))
        else:
            # Not enough history yet, use current measurement
            dark_pixel_smoothed = dark_pixel_value

        # 4. Choose the conservative estimate
        # IMPORTANT: Dark pixels below bias offset are physically impossible
        # (sensor always has electronic pedestal). If we see this, ignore the
        # measurement and use theory instead.
        if dark_pixel_smoothed < self.profile.bias_offset:
            # Measurement is invalid (image too dark or wrong camera settings)
            # Use theoretical estimate instead
            noise_floor = theoretical_noise_floor
            logger.debug(
                f"Dark pixels ({dark_pixel_smoothed:.1f}) below bias offset "
                f"({self.profile.bias_offset:.1f}) - using theoretical estimate"
            )
        else:
            # Valid measurement - take min of measured vs theoretical
            # - If sky is dark, dark pixels ≈ noise floor (good)
            # - If sky is bright, dark pixels > noise floor, use physics model
            noise_floor = min(dark_pixel_smoothed, theoretical_noise_floor)

        # 5. Enforce absolute minimum at bias offset (can't be lower than pedestal)
        noise_floor = max(noise_floor, self.profile.bias_offset)

        # 6. Validate the estimate
        is_valid, reason = self._validate_estimate(noise_floor, image)

        # 7. Build diagnostic details
        details = {
            "noise_floor_adu": noise_floor,
            "dark_pixel_raw": dark_pixel_value,
            "dark_pixel_smoothed": dark_pixel_smoothed,
            "theoretical_floor": theoretical_noise_floor,
            "temporal_noise": temporal_noise,
            "read_noise": self.profile.read_noise_adu,
            "dark_current_contribution": temporal_noise - self.profile.read_noise_adu,
            "bias_offset": self.profile.bias_offset,
            "exposure_sec": exposure_sec,
            "percentile": percentile,
            "n_history_samples": len(self.dark_pixel_history),
            "method": "adaptive_percentile",
            "is_valid": is_valid,
            "validation_reason": reason,
        }

        # 8. Check if we should request zero-second sample
        if self.enable_zero_sec and self._should_sample_zero_sec():
            details["request_zero_sec_sample"] = True
            logger.debug("Requesting zero-second calibration sample")

        if not is_valid:
            logger.warning(
                f"Noise floor estimate may be invalid: {reason} "
                f"(floor={noise_floor:.1f}, median={np.median(image):.1f})"
            )

        return noise_floor, details

    def _estimate_temporal_noise(
        self,
        exposure_sec: float,
    ) -> float:
        """
        Estimate temporal noise from camera physics.

        Components:
        - Read noise (constant, independent of exposure)
        - Dark current (scales with exposure time, assumes ~20°C ambient)

        Formula:
            σ_temporal = σ_read + (I_dark * t)

        Where:
            σ_read = read noise [ADU]
            I_dark = dark current rate [ADU/s] at ~20°C
            t = exposure time [s]

        NOTE: No temperature correction applied (only CPU temp available,
              not sensor temp). This assumes typical ambient temperature.
              In reality, dark current may vary ±50% with ambient temperature.

        Returns:
            Estimated temporal noise in ADU
        """
        # Read noise (constant)
        read_noise = self.profile.read_noise_adu

        # Dark current (linear with exposure, assumes ~20°C)
        dark_current = self.profile.dark_current_rate * exposure_sec

        return read_noise + dark_current

    def _should_sample_zero_sec(self) -> bool:
        """
        Check if we should request a zero-second calibration sample.

        Returns True if it's been longer than zero_sec_interval since the last sample.
        """
        now = time.time()
        if now - self.last_zero_sec_time > self.zero_sec_interval:
            self.last_zero_sec_time = now
            return True
        return False

    def update_with_zero_sec_sample(self, zero_sec_image: np.ndarray) -> None:
        """
        Update calibration from a zero-second exposure.

        A 0-second exposure captures only:
        - Bias offset (electronic pedestal)
        - Read noise (random variation)

        This gives us a direct measurement without dark current or sky background.

        Args:
            zero_sec_image: Image captured with 0-second exposure
        """
        # Measure statistics
        measured_bias = float(np.median(zero_sec_image))
        measured_std = float(np.std(zero_sec_image))

        self.zero_sec_history.append(
            {
                "bias": measured_bias,
                "read_noise": measured_std,
                "timestamp": time.time(),
            }
        )

        logger.info(
            f"Zero-sec sample: bias={measured_bias:.1f} ADU, "
            f"read_noise={measured_std:.2f} ADU"
        )

        # Update profile if we have enough samples
        if len(self.zero_sec_history) >= 3:
            # Use median of recent samples
            recent_bias = [s["bias"] for s in self.zero_sec_history]
            recent_noise = [s["read_noise"] for s in self.zero_sec_history]

            avg_bias = float(np.median(recent_bias))
            avg_read_noise = float(np.median(recent_noise))

            # Gradually adjust profile using exponential moving average
            # This prevents sudden jumps from single noisy measurements
            alpha = 0.2  # Smoothing factor (0.2 = 80% old, 20% new)

            old_bias = self.profile.bias_offset
            old_noise = self.profile.read_noise_adu

            self.profile.bias_offset = (
                alpha * avg_bias + (1 - alpha) * self.profile.bias_offset
            )
            self.profile.read_noise_adu = (
                alpha * avg_read_noise + (1 - alpha) * self.profile.read_noise_adu
            )

            logger.info(
                f"Updated camera profile: "
                f"bias {old_bias:.1f} → {self.profile.bias_offset:.1f}, "
                f"read_noise {old_noise:.2f} → {self.profile.read_noise_adu:.2f}"
            )

    def _validate_estimate(
        self, noise_floor: float, image: np.ndarray
    ) -> Tuple[bool, str]:
        """
        Validate that the noise floor estimate is reasonable.

        Checks:
        1. At or above bias offset (enforced by min constraint, this is just a sanity check)
        2. Below image median (shouldn't be pure noise if we see stars)
        3. Not impossibly high (sanity check)

        Returns:
            (is_valid, reason)
        """
        # Check 1: Should be at or above bias offset (sanity check - already enforced)
        if noise_floor < self.profile.bias_offset:
            return (
                False,
                f"Below bias offset ({self.profile.bias_offset:.1f}) - logic error",
            )

        # Check 2: Should be well below image median
        image_median = float(np.median(image))
        if noise_floor > image_median * 0.8:
            return (
                False,
                f"Too close to median ({image_median:.1f}), likely no stars detected",
            )

        # Check 3: Shouldn't be impossibly high
        max_reasonable = self.profile.bias_offset + self.profile.read_noise_adu * 20
        if noise_floor > max_reasonable:
            return False, f"Exceeds reasonable maximum ({max_reasonable:.1f})"

        return True, "OK"

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about estimation quality.

        Returns:
            Dictionary with diagnostic information
        """
        stats = {
            "camera_type": self.camera_type,
            "n_estimates": self.n_estimates,
            "n_history_samples": len(self.dark_pixel_history),
            "n_zero_sec_samples": len(self.zero_sec_history),
            "current_bias_offset": self.profile.bias_offset,
            "current_read_noise": self.profile.read_noise_adu,
            "current_dark_current": self.profile.dark_current_rate,
        }

        if self.dark_pixel_history:
            history_array = np.array(list(self.dark_pixel_history))
            stats["dark_pixel_mean"] = float(np.mean(history_array))
            stats["dark_pixel_std"] = float(np.std(history_array))
            stats["dark_pixel_median"] = float(np.median(history_array))

        return stats

    def load_calibration(self) -> bool:
        """
        Load saved calibration data from file.

        Returns:
            True if calibration was loaded successfully, False otherwise
        """
        try:
            # Load from ~/PiFinder_data/sqm_calibration_{camera_type}.json
            data_dir = Path.home() / "PiFinder_data"
            calibration_file = data_dir / f"sqm_calibration_{self.camera_type}.json"

            if not calibration_file.exists():
                logger.info(
                    f"No saved calibration found for {self.camera_type}, using default profile"
                )
                return False

            with open(calibration_file, "r") as f:
                calibration_data = json.load(f)

            # Update profile with calibration data
            if "bias_offset" in calibration_data:
                self.profile.bias_offset = calibration_data["bias_offset"]

            if "read_noise" in calibration_data:
                self.profile.read_noise_adu = calibration_data["read_noise"]

            if "dark_current_rate" in calibration_data:
                self.profile.dark_current_rate = calibration_data["dark_current_rate"]

            logger.info(
                f"Loaded calibration: bias={self.profile.bias_offset:.1f}, "
                f"read_noise={self.profile.read_noise_adu:.2f}, "
                f"dark_current={self.profile.dark_current_rate:.3f}"
            )

            return True

        except Exception as e:
            logger.warning(f"Failed to load calibration: {e}")
            return False

    def save_calibration(
        self, bias_offset: float, read_noise: float, dark_current_rate: float
    ) -> bool:
        """
        Save calibration data to file and update profile.

        Args:
            bias_offset: Measured bias offset in ADU
            read_noise: Measured read noise in ADU
            dark_current_rate: Measured dark current rate in ADU/s

        Returns:
            True if calibration was saved successfully, False otherwise
        """
        try:
            calibration_data = {
                "bias_offset": float(bias_offset),
                "read_noise": float(read_noise),
                "dark_current_rate": float(dark_current_rate),
                "camera_type": self.camera_type,
                "timestamp": time.time(),
            }

            # Save to ~/PiFinder_data/sqm_calibration_{camera_type}.json
            data_dir = Path.home() / "PiFinder_data"
            data_dir.mkdir(exist_ok=True)

            calibration_file = data_dir / f"sqm_calibration_{self.camera_type}.json"
            with open(calibration_file, "w") as f:
                json.dump(calibration_data, f, indent=2)

            # Update profile
            self.profile.bias_offset = bias_offset
            self.profile.read_noise_adu = read_noise
            self.profile.dark_current_rate = dark_current_rate

            logger.info(
                f"Saved calibration: bias={bias_offset:.1f}, "
                f"read_noise={read_noise:.2f}, "
                f"dark_current={dark_current_rate:.3f}"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to save calibration: {e}")
            return False

    def reset(self) -> None:
        """Reset all history and statistics."""
        self.dark_pixel_history.clear()
        self.zero_sec_history.clear()
        self.n_estimates = 0
        self.last_zero_sec_time = 0.0
        logger.info("Noise floor estimator reset")
