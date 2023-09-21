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

    def __init__(self) -> None:
        self.camera_type = "none"
        self.camType = f"None {self.camera_type}"
        self.image = Image.new("RGB", (128, 128))
        self.initialize()

    def initialize(self) -> None:
        """Initializes the camera and set the needed control parameters"""
        return

    def capture(self) -> Image.Image:
        return self.image

    def capture_file(self, filename) -> None:
        print("capture_file not implemented")

    def set_camera_config(
        self, exposure_time: float, gain: float
    ) -> Tuple[float, float]:
        return exposure_time, gain

    def get_cam_type(self) -> str:
        return self.camType


def get_images(shared_state, camera_image, command_queue, console_queue):
    """
    Instantiates the camera hardware
    then calls the universal image loop
    """
    cfg = config.Config()
    camera_hardware = CameraNone()
    camera_hardware.get_image_loop(
        shared_state, camera_image, command_queue, console_queue, cfg
    )
