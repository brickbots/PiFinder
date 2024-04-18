#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the camera
* Captures images
* Places preview images in queue
* Places solver images in queue
* Takes full res images on demand

"""
import os
import queue
import time
from PIL import Image
from PiFinder import config
from PiFinder import utils
from PiFinder.camera_interface import CameraInterface
from typing import Tuple


class CameraPI(CameraInterface):
    """The camera class for PI cameras.  Implements the CameraInterface interface."""

    def __init__(self, exposure_time, gain) -> None:
        from picamera2 import Picamera2

        self.camera = Picamera2()
        # Figure out camera type, hq or gs (global shutter)
        self.camera_type = "hq"
        self.camType = f"PI {self.camera_type}"
        self.exposure_time = exposure_time
        self.gain = gain
        self.initialize()

    def initialize(self) -> None:
        """Initializes the camera and set the needed control parameters"""
        self.camera.stop()
        # using this smaller scale auto-selects binning on the sensor...
        cam_config = self.camera.create_still_configuration({"size": (512, 512)}, raw={"size": (2028, 1520), "format": "SRGGB10"})
        #cam_config = self.camera.create_still_configuration({"size": (2028, 1520)})

        self.camera.configure(cam_config)
        self.camera.set_controls({"AeEnable": False})
        self.camera.set_controls({"AnalogueGain": self.gain})
        self.camera.set_controls({"ExposureTime": self.exposure_time})
        self.camera.start()

    def capture(self) -> Image.Image:
        _request = self.camera.capture_request
        _image = _request.make_image("main")
        _raw = _request.make_array("raw")
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


def get_images(shared_state, camera_image, command_queue, console_queue):
    """
    Instantiates the camera hardware
    then calls the universal image loop
    """

    cfg = config.Config()
    exposure_time = cfg.get_option("camera_exp")
    gain = cfg.get_option("camera_gain")
    camera_hardware = CameraPI(exposure_time, gain)
    camera_hardware.get_image_loop(
        shared_state, camera_image, command_queue, console_queue, cfg
    )
