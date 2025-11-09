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
from typing import Tuple
import logging
from PiFinder.multiproclogging import MultiprocLogging
import numpy as np

logger = logging.getLogger("Camera.Pi")


class CameraPI(CameraInterface):
    """The camera class for PI cameras.  Implements the CameraInterface interface."""

    def __init__(self, exposure_time) -> None:
        from picamera2 import Picamera2

        self.camera = Picamera2()

        self.exposure_time = exposure_time
        self.format = "SRGGB12"
        self.bit_depth = 12
        self.digital_gain = 1.0  # TODO: find optimum value for imx296 and imx290
        self.offset = 0  # TODO: measure offset for imx296 and imx290

        # Figure out camera type, hq or imx296 (global shutter)
        if "imx296" in self.camera.camera.id:
            self.camera_type = "imx296"
            # The auto selected 728x544 sensor mode returns black frames if the
            # exposure is too high
            self.raw_size = (1456, 1088)
            self.format = "R10"
            self.bit_depth = 10
            # maximum analog gain for this sensor
            self.gain = 15
        elif "imx290" in self.camera.camera.id:
            self.camera_type = "imx462"
            self.raw_size = (1920, 1080)
            self.gain = 30
        elif "imx477" in self.camera.camera.id:
            self.camera_type = "hq"
            # using this smaller scale auto-selects binning on the sensor
            self.raw_size = (2028, 1520)
            self.gain = 22  # cedar uses this value
            self.digital_gain = (
                13.0  # initial tests show that higher values don't help much
            )
            self.offset = (
                256  # measured with lens cap on, matches what the internet says
            )
        else:
            raise Exception(f"Unknown camera type: {self.camera.camera.id}")

        self.camType = f"PI {self.camera_type}"
        self.initialize()

    def initialize(self) -> None:
        """Initializes the camera and set the needed control parameters"""
        self.stop_camera()
        cam_config = self.camera.create_still_configuration(
            {"size": (512, 512)},
            raw={"size": self.raw_size, "format": self.format},
        )
        self.camera.configure(cam_config)
        self.camera.set_controls({"AeEnable": False})
        self.camera.set_controls({"AnalogueGain": self.gain})
        self.camera.set_controls({"ExposureTime": self.exposure_time})
        self.start_camera()

    def start_camera(self) -> None:
        self.camera.start()
        self._camera_started = True

    def stop_camera(self) -> None:
        self.camera.stop()
        self._camera_started = False

    def capture(self) -> Image.Image:
        """
        Captures a raw 10/12bit sensor output and converts
        it to an 8 bit mono image stretched to use the maximum
        amount of the 255 level space.
        """
        _request = self.camera.capture_request()
        # raw is actually 16 bit
        raw_capture = _request.make_array("raw").copy().view(np.uint16)
        # tmp_image = _request.make_image("main")

        # Log actual camera metadata for exposure verification (debug level only)
        metadata = _request.get_metadata()
        actual_exposure = metadata.get("ExposureTime", "unknown")
        actual_gain = metadata.get("AnalogueGain", "unknown")
        logger.debug(
            f"Captured frame - Requested: {self.exposure_time}µs/{self.gain}x gain, "
            f"Actual: {actual_exposure}µs/{actual_gain:.2f}x gain"
        )

        _request.release()
        # crop to square
        if self.camera_type == "imx296":
            raw_capture = raw_capture[:, 184:-184]
            # Sensor orientation is different
            raw_capture = np.rot90(raw_capture, 2)
        elif self.camera_type == "imx462":
            raw_capture = raw_capture[50:-50, 470:-470]
        elif self.camera_type == "hq":
            raw_capture = raw_capture[:, 256:-256]

        # covert to 32 bit int to avoid overflow
        raw_capture = raw_capture.astype(np.float32)

        # sensor offset, measured as average value when lens cap is on
        raw_capture -= self.offset

        # apply digital gain
        raw_capture *= self.digital_gain

        # rescale to 8 bit
        raw_capture = raw_capture * 255 / (2**self.bit_depth - self.offset - 1)

        # clip to avoid <0 or >255 values
        raw_capture = np.clip(raw_capture.astype(np.int32), 0, 255).astype(np.uint8)

        # convert to PIL image and resize to 512x512
        raw_image = Image.fromarray(raw_capture).resize((512, 512))

        return raw_image

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

        # Crop to square (preserves Bayer pattern alignment if applicable)
        if self.camera_type == "imx296":
            raw_capture = raw_capture[:, 184:-184]
            # Sensor orientation is different
            raw_capture = np.rot90(raw_capture, 2)
        elif self.camera_type == "imx462":
            raw_capture = raw_capture[50:-50, 470:-470]
        elif self.camera_type == "hq":
            raw_capture = raw_capture[:, 256:-256]

        # Determine if we need to flag for debayering based on camera type
        # imx296: Mono sensor (R10 format)
        # imx462: Bayer sensor (SRGGB12 format)
        # HQ (imx477): Bayer sensor (SRGGB12 format)
        needs_debayer = self.camera_type in ("imx462", "hq")

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
        elif raw_capture.ndim != 2:
            raise ValueError(f"Unexpected raw image dimensions: {raw_capture.ndim}")

        # Add camera type and Bayer pattern info to filename
        import os
        base, ext = os.path.splitext(filename)

        # Add camera type suffix (imx296_mono, imx462_bayer, hq_bayer)
        camera_suffix = f"_{self.camera_type}"
        if needs_debayer:
            camera_suffix += "_RGGB"
        else:
            camera_suffix += "_mono"

        filename = f"{base}{camera_suffix}{ext}"

        # Save as 16-bit TIFF
        raw_image = Image.fromarray(raw_capture, mode="I;16")
        raw_image.save(filename, format="TIFF")

        debayer_note = " (RGGB Bayer pattern)" if needs_debayer else ""
        logger.debug(
            f"Saved raw {self.bit_depth}-bit image as 16-bit TIFF: {filename}{debayer_note}"
        )

    def set_camera_config(
        self, exposure_time: float, gain: float
    ) -> Tuple[float, float]:
        # picamera2 supports changing controls on-the-fly without restart
        # This allows seamless auto-exposure adjustments
        logger.info(
            f"Setting camera config - Exposure: {exposure_time}µs, Gain: {gain}x "
            f"(camera_started: {self._camera_started})"
        )
        if self._camera_started:
            self.camera.set_controls({"AnalogueGain": gain})
            self.camera.set_controls({"ExposureTime": exposure_time})
        else:
            # Camera not started, need to stop/start
            self.stop_camera()
            self.camera.set_controls({"AnalogueGain": gain})
            self.camera.set_controls({"ExposureTime": exposure_time})
            self.start_camera()
        return exposure_time, gain

    def get_cam_type(self) -> str:
        return self.camType


def get_images(shared_state, camera_image, command_queue, console_queue, log_queue):
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
        shared_state, camera_image, command_queue, console_queue, cfg
    )
