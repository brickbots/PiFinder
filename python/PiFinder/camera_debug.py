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
from PiFinder import utils
from PiFinder.camera_interface import CameraInterface
from typing import Tuple
import time
import logging


class CameraDebug(CameraInterface):
    """The debug camera class.  Implements the CameraInterface interface.

    Loads an image from disk and returns it for each exposure

    """

    def __init__(self, exposure_time) -> None:
        print("init camera debug")
        self.camType = "Debug camera"
        self.path = utils.pifinder_dir / "test_images"
        self.exposure_time = exposure_time
        self.gain = 10
        self.image = Image.open(self.path / "pifinder_debug.png")
        self.initialize()

    def initialize(self) -> None:
        pass

    def capture(self) -> Image.Image:
        sleep_time = self.exposure_time / 1000000
        time.sleep(sleep_time)
        logging.debug("CameraDebug exposed for %s seconds", sleep_time)
        return self.image

    def capture_file(self, filename) -> None:
        print("capture_file not implemented")
        pass

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
    exposure_time = cfg.get_option("camera_exp")
    camera_hardware = CameraDebug(exposure_time)
    camera_hardware.get_image_loop(
        shared_state, camera_image, command_queue, console_queue, cfg
    )
