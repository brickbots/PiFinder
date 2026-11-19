"""Detector baseline and operational noise-threshold estimation.

The bias and, when measured, mean dark signal define the applied detector
pedestal. Read noise is a random RMS quantity, not another pedestal component.
The published ``noise_floor_adu`` is therefore a one-read-noise-sigma threshold
above the pedestal. Image percentiles remain useful diagnostics, but cannot
separate detector signal from real sky signal and are never used as dark
calibration.
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
    Estimate the detector pedestal and an operational background threshold.

    ``bias_offset + calibrated_dark_current_rate * exposure_sec`` is the mean
    signal to subtract from a science image. Factory dark-current values are
    unverified engineering estimates, so the exposure-dependent term is
    enabled only after a per-device calibration has measured it.
    ``read_noise_adu`` is an RMS uncertainty. These quantities remain separate
    in diagnostics.
    """

    def __init__(
        self,
        camera_type: str,
        history_size: int = 20,
        enable_zero_sec_sampling: bool = False,
        zero_sec_interval: int = 300,  # 5 minutes
    ):
        """
        Initialize the noise floor estimator.

        Args:
            camera_type: Camera model (imx296, imx462, imx290, hq)
            history_size: Number of recent measurements to track for smoothing
            enable_zero_sec_sampling: Whether to emit periodic 0-sec requests.
                No runtime camera path services them; use only when the caller
                explicitly consumes ``request_zero_sec_sample``.
            zero_sec_interval: Seconds between zero-second calibration samples
        """
        self.camera_type = camera_type
        self.profile = get_camera_profile(camera_type)
        self.calibration_loaded = False
        self.dark_current_calibrated = False

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
        self.calibration_loaded = self.load_calibration()

    def estimate_noise_floor(
        self,
        image: np.ndarray,
        exposure_sec: float,
        percentile: float = 5.0,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Estimate noise floor from an actual sky image.

        The calibrated detector model supplies the result. The image's low
        percentile is tracked only to diagnose calibration or exposure
        problems; even the darkest sky pixels still contain sky signal and
        cannot directly measure the detector pedestal.

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

        # Track the darkest image pixels as an exposure/calibration diagnostic.
        # They still contain real sky signal.
        dark_pixel_value = float(np.percentile(image, percentile))
        self.dark_pixel_history.append(dark_pixel_value)

        # The calibrated pedestal is mean bias + mean accumulated dark signal.
        # Dark shot noise needs a conversion gain in electrons/ADU, which the
        # profiles do not yet provide, so only read noise is in the RMS term.
        dark_current_model_contribution = self.profile.dark_current_rate * exposure_sec
        dark_current_contribution = (
            dark_current_model_contribution if self.dark_current_calibrated else 0.0
        )
        pedestal = self.profile.bias_offset + dark_current_contribution
        temporal_noise = self._estimate_temporal_noise(exposure_sec)
        theoretical_noise_floor = pedestal + temporal_noise

        # 3. Smoothed measurement from history
        if len(self.dark_pixel_history) >= 5:
            # Use median for robustness against outliers
            dark_pixel_smoothed = float(np.median(list(self.dark_pixel_history)))
        else:
            # Not enough history yet, use current measurement
            dark_pixel_smoothed = dark_pixel_value

        # Publish the calibrated one-sigma threshold. Samples below a bias
        # level are normal for zero-mean read noise, not physically impossible.
        noise_floor = theoretical_noise_floor

        # 6. Validate the estimate
        is_valid, reason = self._validate_estimate(noise_floor, image)

        # 7. Build diagnostic details
        details = {
            "noise_floor_adu": noise_floor,
            "dark_pixel_raw": dark_pixel_value,
            "dark_pixel_smoothed": dark_pixel_smoothed,
            "theoretical_floor": theoretical_noise_floor,
            "pedestal": pedestal,
            "temporal_noise": temporal_noise,
            "read_noise": self.profile.read_noise_adu,
            "dark_current_contribution": dark_current_contribution,
            "dark_current_model_contribution": dark_current_model_contribution,
            "dark_current_calibrated": self.dark_current_calibrated,
            "bias_offset": self.profile.bias_offset,
            "exposure_sec": exposure_sec,
            "percentile": percentile,
            "n_history_samples": len(self.dark_pixel_history),
            "method": "calibrated_detector_model",
            "is_valid": is_valid,
            "validation_reason": reason,
        }

        # 8. Check if we should request zero-second sample
        if self.enable_zero_sec and self._should_sample_zero_sec():
            details["request_zero_sec_sample"] = True
            logger.debug("Requesting zero-second calibration sample")

        if not is_valid:
            logger.debug(
                f"Noise floor estimate may be invalid: {reason} "
                f"(floor={noise_floor:.1f}, median={np.median(image):.1f})"
            )

        return noise_floor, details

    def _estimate_temporal_noise(
        self,
        exposure_sec: float,
    ) -> float:
        """
        Return the calibrated RMS read noise in ADU.

        Mean dark signal belongs to the pedestal, not the RMS noise term. Dark
        shot noise can be added in quadrature after conversion gain is known.

        Returns:
            Estimated temporal noise in ADU
        """
        del exposure_sec
        return self.profile.read_noise_adu

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

        logger.debug(
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
            self.calibration_loaded = True

            logger.debug(
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
        1. At or above the calibrated pedestal.
        2. Below the image median, so the current frame resolves signal above
           the operational threshold.

        Returns:
            (is_valid, reason)
        """
        expected_pedestal = self.profile.bias_offset
        if noise_floor < expected_pedestal:
            return (
                False,
                f"Below bias offset ({expected_pedestal:.1f}) - logic error",
            )

        image_median = float(np.median(image))
        if noise_floor >= image_median:
            return (
                False,
                f"At or above image median ({image_median:.1f}); background unresolved",
            )

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
            "calibration_loaded": self.calibration_loaded,
            "dark_current_calibrated": self.dark_current_calibrated,
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

            known_fields = {"bias_offset", "read_noise", "dark_current_rate"}
            if not known_fields.intersection(calibration_data):
                raise ValueError("calibration contains no detector values")

            # Parse and validate everything before mutation. A bad dark field
            # must not leave a valid-looking bias override partially applied.
            bias_offset = float(
                calibration_data.get("bias_offset", self.profile.bias_offset)
            )
            read_noise = float(
                calibration_data.get("read_noise", self.profile.read_noise_adu)
            )
            dark_current_rate = float(
                calibration_data.get(
                    "dark_current_rate", self.profile.dark_current_rate
                )
            )
            if not np.isfinite(bias_offset):
                raise ValueError("bias_offset must be finite")
            if not np.isfinite(read_noise) or read_noise < 0:
                raise ValueError("read_noise must be finite and non-negative")
            if not np.isfinite(dark_current_rate) or dark_current_rate < 0:
                raise ValueError("dark_current_rate must be finite and non-negative")

            self.profile.bias_offset = bias_offset
            self.profile.read_noise_adu = read_noise
            self.profile.dark_current_rate = dark_current_rate
            self.dark_current_calibrated = "dark_current_rate" in calibration_data

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
            bias_offset = float(bias_offset)
            read_noise = float(read_noise)
            dark_current_rate = float(dark_current_rate)
            if not np.isfinite(bias_offset):
                raise ValueError("bias_offset must be finite")
            if not np.isfinite(read_noise) or read_noise < 0:
                raise ValueError("read_noise must be finite and non-negative")
            if not np.isfinite(dark_current_rate) or dark_current_rate < 0:
                raise ValueError("dark_current_rate must be finite and non-negative")

            calibration_data = {
                "bias_offset": bias_offset,
                "read_noise": read_noise,
                "dark_current_rate": dark_current_rate,
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
            self.calibration_loaded = True
            self.dark_current_calibrated = True

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
