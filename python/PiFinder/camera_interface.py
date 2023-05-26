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


class CameraInterface:
    """The CameraInterface interface."""

    def initialize(self) -> None:
        pass

    def capture(self) -> Image.Image:
        return None

    def capture_file(self, filename) -> None:
        pass

    def set_camera_config(self, exposure_time: float, gain: float) -> None:
        pass

    def get_cam_type(self) -> str:
        pass
