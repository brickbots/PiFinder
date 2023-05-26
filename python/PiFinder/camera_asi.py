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


class CameraASI(CameraInterface):
    """The camera class for PI cameras.  Implements the CameraInterface interface."""

    def __init__(self) -> None:
        from picamera2 import Picamera2
        self.camera = Picamera2()
        # Figure out camera type, hq or gs (global shutter)
        self.camera_type = "hq"
        gain_mult = 1
        self.sensor_modes = camera.sensor_modes
        if len(sensor_modes) == 1:
            gain_mult = 3
            camera_type = "gs"
        self.camType = f"PI {camera_type}"

    def initialize(self) -> None:
        """Initializes the camera and set the needed control parameters"""
        self.camera.stop()
        # using this smaller scale auto-selects binning on the sensor...
        cam_config = self.camera.create_still_configuration({"size": (512, 512)})
        self.camera.configure(cam_config)
        self.camera.set_controls({"AeEnable": False})
        self.camera.set_controls({"AnalogueGain": analog_gain})
        self.camera.set_controls({"ExposureTime": exposure_time})
        self.camera.start()

    def capture(self) -> Image.Image:
        return self.camera.capture_image()

    def capture_file(self, filename) -> None:
        return self.camera.capture_file(filename)

    def set_camera_config(self, exposure_time: float, gain: float) -> None:
        self.camera.stop()
        self.camera.set_controls({"AnalogueGain": gain})
        self.camera.set_controls({"ExposureTime": exposure_time})
        self.camera.start()

    def get_cam_type(self) -> str:
        return self.camType
