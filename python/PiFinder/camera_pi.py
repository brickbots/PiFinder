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

    def capture_bias(self) -> Image.Image:
        """Capture a bias frame for dark subtraction"""
        self.camera.stop()
        self.camera.set_controls({"ExposureTime": 0})
        self.camera.start()
        tmp_capture = self.camera.capture_image()
        self.camera.stop()
        self._default_controls()
        self.camera.start()
        print("Bias frame has {np.mean(tmp_capture)=}, {np.std(tmp_capture)=}, {np.max(tmp_capture)=}, {np.min(tmp_capture)=}, {np.median(tmp_capture)=}")
        return tmp_capture

    def capture_file(self, filename) -> None:
        tmp_capture = self.capture()
        tmp_capture.save(filename)

    def set_camera_config(
        self, exposure_time: float, gain: float
    ) -> Tuple[float, float]:
        self.stop_camera()
        self.camera.set_controls({"AnalogueGain": gain})
        self.camera.set_controls({"ExposureTime": exposure_time})
        self.start_camera()
        return exposure_time, gain

    def get_cam_type(self) -> str:
        return self.camType


def get_images(shared_state, camera_image, bias_image, command_queue, console_queue, log_queue):
    """
    Instantiates the camera hardware
    then calls the universal image loop
    """
    MultiprocLogging.configurer(log_queue)

    cfg = config.Config()
    exposure_time = cfg.get_option("camera_exp")
    camera_hardware = CameraPI(exposure_time)
    camera_hardware.get_image_loop(
        shared_state, camera_image, bias_image, command_queue, console_queue, cfg
    )
