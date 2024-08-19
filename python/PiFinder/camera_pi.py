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

logger = logging.getLogger("Camera.Pi")


class CameraPI(CameraInterface):
    """The camera class for PI cameras.  Implements the CameraInterface interface."""

    def __init__(self, exposure_time) -> None:
        from picamera2 import Picamera2

        self.camera = Picamera2()
        # Figure out camera type, hq or imx296 (global shutter)
        self.camera_type = "hq"
        self.gain = 20
        self.exposure_time = exposure_time
        if "imx296" in self.camera.camera.id:
            self.camera_type = "imx296"
            # maximum analog gain for this sensor
            self.gain = 15
        self.camType = f"PI {self.camera_type}"
        self.initialize()

    def initialize(self) -> None:
        """Initializes the camera and set the needed control parameters"""
        self.camera.stop()
        if self.camera_type == "imx296":
            # The auto selected 728x544 sensor mode returns black frames if the
            # exposure is too high.  So we need to force a specific sensor
            # mode by specifying a raw stream we won't use
            cam_config = self.camera.create_still_configuration(
                {
                    "size": (512, 512),
                },
                raw={"size": (1456, 1088)},
            )
        else:
            # using this smaller scale auto-selects binning on the sensor...
            cam_config = self.camera.create_still_configuration({"size": (512, 512)})
        self.camera.configure(cam_config)
        self.camera.set_controls({"AeEnable": False})
        self.camera.set_controls({"AnalogueGain": self.gain})
        self.camera.set_controls({"ExposureTime": self.exposure_time})
        self.camera.start()

    def capture(self) -> Image.Image:
        return self.camera.capture_image()

    def capture_file(self, filename) -> None:
        return self.camera.capture_file(filename)

    def set_camera_config(
        self, exposure_time: float, gain: float
    ) -> Tuple[float, float]:
        self.camera.stop()
        self.camera.set_controls({"AnalogueGain": gain})
        self.camera.set_controls({"ExposureTime": exposure_time})
        self.camera.start()
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
    camera_hardware = CameraPI(exposure_time)
    camera_hardware.get_image_loop(
        shared_state, camera_image, command_queue, console_queue, cfg
    )
