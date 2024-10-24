#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the camera
* Captures images
* Places preview images in queue
* Places solver images in queue
* Takes full res images on demand

"""

import time
from PIL import Image
from PiFinder import config
from PiFinder.camera_interface import CameraInterface
from typing import Tuple
import logging

logger = logging.getLogger("Camera.None")


class CameraNone(CameraInterface):
    """Simulate a camera not solving"""

    def __init__(self, exposure_time) -> None:
        self.camera_type = "none"
        self.camType = f"None {self.camera_type}"
        self.exposure_time = exposure_time
        self.image = Image.new("RGB", (128, 128))
        self.initialize()

    def initialize(self) -> None:
        """Initializes the camera and set the needed control parameters"""
        return

    def capture(self) -> Image.Image:
        sleep_time = self.exposure_time / 1000000
        time.sleep(sleep_time)
        logger.debug("CameraNone exposed for %s seconds", sleep_time)
        return self.image

    def capture_file(self, filename) -> None:
        logger.warning("capture_file not implemented")
        pass

    def set_camera_config(
        self, exposure_time: float, gain: float
    ) -> Tuple[float, float]:
        return exposure_time, gain

    def get_cam_type(self) -> str:
        return self.camType


def get_images(shared_state, camera_image, bias_image, command_queue, console_queue):
    """
    Instantiates the camera hardware
    then calls the universal image loop
    """
    cfg = config.Config()
    exposure_time = cfg.get_option("camera_exp")
    camera_hardware = CameraNone(exposure_time)
    camera_hardware.get_image_loop(
        shared_state, camera_image, bias_image, command_queue, console_queue, cfg
    )
