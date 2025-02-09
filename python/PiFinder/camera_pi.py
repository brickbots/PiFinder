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
        # Figure out camera type, hq or imx296 (global shutter)
        self.camera_type = "hq"
        self.gain = 20
        self.exposure_time = exposure_time
        if "imx296" in self.camera.camera.id:
            self.camera_type = "imx296"
            # maximum analog gain for this sensor
            self.gain = 15

        if "imx290" in self.camera.camera.id:
            self.camera_type = "imx462"
            self.gain = 30

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
                raw={"size": (1456, 1088), "format": "R10"},
            )
        elif self.camera_type == "imx462":
            cam_config = self.camera.create_still_configuration(
                {
                    "size": (512, 512),
                },
                raw={"size": (1920, 1080), "format": "SRGGB12"},
            )
        else:
            # using this smaller scale auto-selects binning on the sensor...
            # cam_config = self.camera.create_still_configuration({"size": (512, 512)})
            cam_config = self.camera.create_still_configuration(
                {"size": (512, 512)}, raw={"size": (2028, 1520), "format": "SRGGB12"}
            )
        self.camera.configure(cam_config)
        self.camera.set_controls({"AeEnable": False})
        self.camera.set_controls({"AnalogueGain": self.gain})
        self.camera.set_controls({"ExposureTime": self.exposure_time})
        self.camera.start()

    def capture(self) -> Image.Image:
        """
        Captures a raw 10/12bit sensor output and converts
        it to an 8 bit mono image stretched to use the maximum
        amount of the 255 level space.
        """
        _request = self.camera.capture_request()
        raw_capture = _request.make_array("raw")
        # tmp_image = _request.make_image("main")
        _request.release()
        if self.camera_type == "imx296":
            # crop to square and resample to 16 bit from 2 8 bit entries
            raw_capture = raw_capture.copy().view(np.uint16)[:, 184:-184]
            # Sensor orientation is different
            raw_capture = np.rot90(raw_capture, 2)
        elif self.camera_type == "imx462":
            # crop to square and resample to 16 bit from 2 8 bit entries
            # to get the right FOV, we want a 980 square....
            raw_capture = raw_capture.copy().view(np.uint16)[50:-50, 470:-470]
        else:
            # crop to square and resample to 16 bit from 2 8 bit entries
            raw_capture = raw_capture.copy().view(np.uint16)[:, 256:-256]

        raw_capture = raw_capture.astype(np.float32)
        max_pixel = np.max(raw_capture)

        # if the whitepoint is already below 255, just cast it
        # as we don't want to create fake in-between values
        if max_pixel < 255:
            raw_capture = raw_capture.astype(np.uint8)
        else:
            raw_capture = (raw_capture / max_pixel * 255).astype(np.uint8)

        raw_image = Image.fromarray(raw_capture).resize((512, 512))
        return raw_image

    def capture_file(self, filename) -> None:
        tmp_capture = self.capture()
        tmp_capture.save(filename)

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
