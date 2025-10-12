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
from itertools import cycle

from PiFinder.multiproclogging import MultiprocLogging

logger = logging.getLogger("Camera.Debug")


class CameraDebug(CameraInterface):
    """The debug camera class.  Implements the CameraInterface interface.

    Cycles through three images stored in "test_images" every 5 secs.

    """

    def __init__(self, exposure_time) -> None:
        logger.debug("init camera debug")
        self.camType = "Debug camera"
        self.path = utils.pifinder_dir / "test_images"
        self.exposure_time = exposure_time
        self.gain = 10
        self.image_bool = True
        self.setup_debug_images()
        self.initialize()

    def setup_debug_images(self) -> None:
        self.image1 = Image.open(self.path / "debug1.png")
        self.image2 = Image.open(self.path / "debug2.png")
        self.image3 = Image.open(self.path / "debug3.png")
        self.images = [self.image1, self.image2, self.image3]
        self.image_cycle = cycle(self.images)
        self.last_image_time: float = 0
        self.last_image = self.image2

    def initialize(self) -> None:
        self._camera_started = True

    def start_camera(self) -> None:
        self._camera_started = True

    def stop_camera(self) -> None:
        self._camera_started = False

    def capture(self) -> Image.Image:
        sleep_time = self.exposure_time / 1000000
        time.sleep(sleep_time)
        logger.debug("CameraDebug exposed for %s seconds", sleep_time)
        if time.time() - self.last_image_time > 5:
            self.last_image = next(self.image_cycle)
            self.last_image_time = time.time()
        return self.last_image

    def capture_file(self, filename) -> None:
        logger.warn("capture_file not implemented in Camera Debug")
        pass

    def set_camera_config(
        self, exposure_time: float, gain: float
    ) -> Tuple[float, float]:
        return exposure_time, gain

    def get_cam_type(self) -> str:
        return self.camType


def get_images(shared_state, camera_image, bias_image, command_queue, console_queue, log_queue):
    """
    Instantiates the camera hardware
    then calls the universal image loop
    """
    MultiprocLogging.configurer(log_queue)
    cfg = config.Config()
    exposure_time = cfg.get_option("camera_exp")
    camera_hardware = CameraDebug(exposure_time)
    camera_hardware.get_image_loop(shared_state, camera_image, bias_image, command_queue, console_queue, cfg)
