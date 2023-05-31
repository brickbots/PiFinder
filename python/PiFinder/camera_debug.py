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
import PiFinder.utils
from typing import Tuple


class CameraDebug(CameraInterface):
    """The camera class for PI cameras.  Implements the CameraInterface interface."""

    def __init__(self) -> None:
        self.camType = "Debug camera"
        self.path = utils.pifinder_dir / "test_images"

    def initialize(self) -> None:
        pass

    def capture(self) -> Image.Image:
        return Image.open(self.path / "pifinder_debug.png")

    def capture_file(self, filename) -> None:
        print("capture_file not implemented")
        pass

    def set_camera_config(
        self, exposure_time: float, gain: float
    ) -> Tuple[float, float, float]:
        return exposure_time, gain, gain

    def get_cam_type(self) -> str:
        return self.camType
