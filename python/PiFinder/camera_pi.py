#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the camera
* Captures images
* Places preview images in queue
* Places solver images in queue
* Takes full res images on demand

"""

from PIL import Image
from PiFinder import config
from PiFinder.camera_interface import CameraInterface
from PiFinder.sqm import get_camera_profile, detect_camera_type
from PiFinder.sqm.radiometer import collect_radiometer_sample
from typing import Tuple
import logging
from PiFinder.multiproclogging import MultiprocLogging
import numpy as np
import time

logger = logging.getLogger("Camera.Pi")


class CameraPI(CameraInterface):
    """The camera class for PI cameras.  Implements the CameraInterface interface."""

    def __init__(self, exposure_time) -> None:
        from picamera2 import Picamera2

        self.camera = Picamera2()
        self.exposure_time = exposure_time

        # Detect camera type and load complete profile (hardware config + noise characteristics)
        self.camera_type = detect_camera_type(self.camera.camera.id)
        self.profile = get_camera_profile(self.camera_type)
        logger.info(
            f"Loaded profile for {self.camera_type}: "
            f"{self.profile.format}, {self.profile.raw_size}, "
            f"gain={self.profile.analog_gain:.0f}, dgain={self.profile.digital_gain:.1f}, "
            f"{self.profile.bit_depth}bit, offset={self.profile.bias_offset:.1f} ADU"
        )

        # Initialize runtime gain from profile (can be changed via commands)
        self.gain = self.profile.analog_gain
        self._radiometer_sequence = 0

        self.camType = f"PI {self.camera_type}"
        self.initialize()

    def initialize(self) -> None:
        """Initializes the camera and set the needed control parameters"""
        self.stop_camera()
        cam_config = self.camera.create_still_configuration(
            {"size": (512, 512)},
            raw={"size": self.profile.raw_size, "format": self.profile.format},
        )
        self.camera.configure(cam_config)
        self._default_controls()
        self.start_camera()

    def _default_controls(self) -> None:
        self.camera.set_controls({"AeEnable": False})
        self.camera.set_controls({"AnalogueGain": self.gain})
        self.camera.set_controls({"ExposureTime": self.exposure_time})

    def start_camera(self) -> None:
        self.camera.start()
        self._camera_started = True

    def stop_camera(self) -> None:
        self.camera.stop()
        self._camera_started = False

    def _read_raw(self) -> np.ndarray:
        """Read one raw 10/12bit sensor frame, uncropped."""
        _request = self.camera.capture_request()
        # raw is actually 16 bit
        raw_capture = _request.make_array("raw").copy().view(np.uint16)

        # Log actual camera metadata for exposure verification (debug level only)
        metadata = _request.get_metadata()
        actual_exposure = metadata.get("ExposureTime", "unknown")
        actual_gain = metadata.get("AnalogueGain", "unknown")
        logger.debug(
            f"Captured frame - Requested: {self.exposure_time}µs/{self.gain}x gain, "
            f"Actual: {actual_exposure}µs/{actual_gain:.2f}x gain"
        )
        # Sensor die temperature (diagnostic only): the black level wanders
        # ±2 ADU night-to-night and temperature is the prime suspect. Not all
        # sensors report it (imx296/HQ drivers may omit or mistype the key);
        # temperature must never be able to break a capture.
        try:
            temp = metadata.get("SensorTemperature")
            self.last_sensor_temp = float(temp) if temp is not None else None
        except (TypeError, ValueError):
            self.last_sensor_temp = None
        # Full driver metadata for the latest frame: calibration and sweeps
        # need the ACTUAL ExposureTime (drivers deliver transitional frames at
        # other-than-requested exposures) and whatever else this sensor's
        # driver chooses to report.
        self.last_frame_metadata = metadata

        _request.release()
        return raw_capture

    def _to_8bit(self, raw_capture: np.ndarray) -> np.ndarray:
        """Subtract the bias pedestal and stretch to the full 0-255 range."""
        # covert to 32 bit int to avoid overflow
        raw_capture = raw_capture.astype(np.float32)

        # sensor offset (bias pedestal from camera profile)
        raw_capture -= self.profile.bias_offset

        # apply digital gain
        raw_capture *= self.profile.digital_gain

        # rescale to 8 bit
        raw_capture = (
            raw_capture
            * 255
            / (2**self.profile.bit_depth - self.profile.bias_offset - 1)
        )

        # clip to avoid <0 or >255 values
        return np.clip(raw_capture.astype(np.int32), 0, 255).astype(np.uint8)

    def _display_frame(self, raw_capture: np.ndarray) -> Image.Image:
        """Square-crop the sensor frame down to the 512x512 display frame.

        SQM photometry and the radiometer both measure the crop, so both are
        fed from here rather than from the full-sensor solve frame.
        """
        cropped = self.profile.crop_and_rotate(raw_capture)

        # Reduce the matrix while it is local to the camera process. The solver
        # can publish radiometric SQM from this small sample without a solve and
        # without copying/scanning the raw frame on every capture.
        if hasattr(self, "shared_state"):
            self._radiometer_sequence += 1
            actual_exposure = getattr(self, "last_frame_metadata", {}).get(
                "ExposureTime"
            )
            try:
                radiometer_exposure = float(actual_exposure) / 1_000_000.0
            except (TypeError, ValueError):
                radiometer_exposure = float(self.exposure_time) / 1_000_000.0
            sample = collect_radiometer_sample(
                cropped,
                self.profile,
                radiometer_exposure,
                sequence=self._radiometer_sequence,
                captured_at=time.time(),
            )
            if sample is not None:
                self.shared_state.set_sqm_radiometer_sample(sample)

        # Store raw in shared state (before processing) for calibration and analysis
        if hasattr(self, "shared_state"):
            self.shared_state.set_cam_raw(cropped.copy())

        return Image.fromarray(self._to_8bit(cropped)).resize((512, 512))

    def _solve_frame(self, raw_capture: np.ndarray) -> Image.Image:
        """Full sensor area at native scale, for the plate solver."""
        return Image.fromarray(self._to_8bit(self.profile.full_frame(raw_capture)))

    def capture(self) -> Image.Image:
        """
        Captures a raw 10/12bit sensor output and converts
        it to an 8 bit mono image stretched to use the maximum
        amount of the 255 level space.
        """
        return self._display_frame(self._read_raw())

    def capture_pair(self) -> Tuple[Image.Image, Image.Image]:
        """Produce the display and solve frames from a single sensor read."""
        raw_capture = self._read_raw()
        return self._display_frame(raw_capture), self._solve_frame(raw_capture)

    def capture_bias(self) -> np.ndarray:
        """Capture a bias frame for measuring black level offset.

        Captures with 0µs exposure (lens cap on) to measure sensor black level.
        Returns raw sensor values before any processing.
        """
        self.camera.stop()
        self.camera.set_controls({"ExposureTime": 0})
        self.camera.start()
        _request = self.camera.capture_request()
        raw_capture = _request.make_array("raw").copy().view(np.uint16)
        _request.release()

        self.camera.stop()
        self.camera.set_controls({"AnalogueGain": self.gain})
        self.camera.set_controls({"ExposureTime": self.exposure_time})
        self.camera.start()

        # Crop like normal capture but don't process
        if self.camera_type == "imx296":
            raw_capture = raw_capture[:, 184:-184]
            raw_capture = np.rot90(raw_capture, 2)
        elif self.camera_type == "imx462":
            raw_capture = raw_capture[50:-50, 470:-470]
        elif self.camera_type == "hq":
            raw_capture = raw_capture[:, 256:-256]

        return raw_capture

    def capture_file(self, filename) -> None:
        tmp_capture = self.capture()
        tmp_capture.save(filename)

    def capture_raw_file(self, filename) -> None:
        """
        Captures raw sensor data and saves as 16-bit TIFF.

        For Bayer sensors:
        - Saves raw Bayer mosaic (RGGB pattern)
        - Adds "_RGGB" suffix to filename (indicates Bayer pattern for post-processing)
        - Post-processing can debayer using scikit-image, opencv, etc.

        For RGB sensors:
        - Converts to grayscale
        - Saves without Bayer pattern suffix

        The square crop is never applied here, and there is deliberately no
        option to apply it. The crop is a plain slice, so the full frame is a
        superset and ``profile.ensure_cropped()`` reproduces the cropped frame
        from it exactly -- while margins not written now are gone for good.
        Live photometry is unaffected: it reads ``cam_raw()``, still the crop.
        """
        _request = self.camera.capture_request()
        # raw is actually 16 bit
        raw_capture = _request.make_array("raw").copy().view(np.uint16)

        # Log actual camera metadata for exposure verification (debug level only)
        metadata = _request.get_metadata()
        actual_exposure = metadata.get("ExposureTime", "unknown")
        actual_gain = metadata.get("AnalogueGain", "unknown")
        logger.debug(
            f"Captured raw frame - Requested: {self.exposure_time}µs/{self.gain}x gain, "
            f"Actual: {actual_exposure}µs/{actual_gain:.2f}x gain"
        )

        _request.release()

        # Expose this frame's driver metadata and its CROPPED pixels so the
        # sweep capture can record per-image radiometry (exposure sweeps are
        # the only caller; both are overwritten on every raw capture).
        #
        # Note the asymmetry, and that it is deliberate: the TIFF written below
        # is full-sensor, while these statistics cover the crop. They are the
        # black-level-versus-temperature series, and the vignetted margins
        # would shift every mean and percentile, silently ending comparability
        # with the archive taken before sweeps went full-sensor. Full-sensor
        # statistics stay computable from the TIFF.
        self.last_frame_driver_metadata = metadata
        self.last_cropped_frame = self.profile.crop_and_rotate(raw_capture)

        # Determine if we need to flag for debayering
        needs_debayer = False

        # Handle different input types
        if raw_capture.ndim == 3:
            # Already RGB - convert to grayscale
            logger.debug(
                f"Converting RGB raw data to grayscale (shape: {raw_capture.shape})"
            )
            raw_capture = (
                raw_capture[:, :, 0] * 0.299
                + raw_capture[:, :, 1] * 0.587
                + raw_capture[:, :, 2] * 0.114
            ).astype(np.uint16)
            needs_debayer = False
        elif raw_capture.ndim == 2:
            # Bayer mosaic - save as-is and flag for post-processing
            logger.debug(
                f"Saving raw Bayer mosaic (RGGB pattern, shape: {raw_capture.shape})"
            )
            needs_debayer = True
        else:
            raise ValueError(f"Unexpected raw image dimensions: {raw_capture.ndim}")

        # Modify filename if debayering needed
        if needs_debayer:
            # Insert "_RGGB" suffix before extension to indicate Bayer pattern
            import os

            base, ext = os.path.splitext(filename)
            filename = f"{base}_RGGB{ext}"

        # Save as 16-bit TIFF
        raw_image = Image.fromarray(raw_capture, mode="I;16")
        raw_image.save(filename, format="TIFF")

        debayer_note = " (RGGB Bayer pattern)" if needs_debayer else ""
        logger.debug(
            f"Saved raw {self.profile.bit_depth}-bit image as 16-bit TIFF: {filename}{debayer_note}"
        )

    def set_camera_config(
        self, exposure_time: float, gain: float
    ) -> Tuple[float, float]:
        # picamera2 supports changing controls on-the-fly without restart.
        # Setting a manual exposure always disables native auto-exposure, so a
        # prior `set_exp:native` (daytime align) can't keep overriding it.
        self.camera.set_controls({"AeEnable": False})
        self.camera.set_controls({"AnalogueGain": gain})
        self.camera.set_controls({"ExposureTime": exposure_time})

        # Start camera if it's not already running
        if not self._camera_started:
            self.start_camera()
        return exposure_time, gain

    def set_native_ae(self, enabled: bool) -> bool:
        """Enable/disable picamera2's native auto-exposure (AEC/AGC).

        Used by the daytime alignment screen so the driver picks a short
        daylight exposure automatically. Returns True (Pi cameras support it).
        """
        self.camera.set_controls({"AeEnable": enabled})
        if not self._camera_started:
            self.start_camera()
        return True

    def get_cam_type(self) -> str:
        return self.camType


def get_images(
    shared_state, camera_image, solve_image, command_queue, console_queue, log_queue
):
    """
    Instantiates the camera hardware
    then calls the universal image loop
    """
    MultiprocLogging.configurer(log_queue)

    cfg = config.Config()
    exposure_time = cfg.get_option("camera_exp")

    # Handle auto-exposure mode: use default value, auto-exposure will adjust
    if exposure_time == "auto":
        exposure_time = 400000  # Start with default 400ms

    camera_hardware = CameraPI(exposure_time)
    camera_hardware.get_image_loop(
        shared_state, camera_image, solve_image, command_queue, console_queue, cfg
    )
