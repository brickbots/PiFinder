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


class CameraNone(CameraInterface):
    """Simulate a camera not solving"""

    def __init__(self, exposure_time, gain) -> None:
        self.camera_type = "none"
        self.camType = f"None {self.camera_type}"
        self.exposure_time = exposure_time
        self.gain = gain
        self.initialize()

    def initialize(self) -> None:
        """Initializes the camera and set the needed control parameters"""
        return

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


def get_images(shared_state, camera_image, command_queue, console_queue):
    """
    Instantiates the camera hardware
    then calls the universal image loop
    """
