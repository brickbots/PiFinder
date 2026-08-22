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
        # Format matches PI cameras for compatibility. The sensor named here
        # is the one the frames in test_images/ were actually shot on, which
        # is what makes SQM's profile lookup and the Lens menu resolve to
        # something plausible. It is *not* a claim that this machine has an hq
        # attached, and it does not settle the field of view on its own: the
        # other half of the train comes from config, and a config that states
        # a lens (16mm -> 17.12 deg, 12mm -> 20.43 deg) gates these ~10.2 deg
        # frames straight out. Hence optical_train_known below. See
        # docs/adr/0027 and the third-rung amendment to docs/adr/0029.
        self.camType = "Debug hq"
        self.path = utils.pifinder_dir / "test_images"
        self.exposure_time = exposure_time
        self.gain = 10
        self.image_bool = True
        self.setup_debug_images()
        self.initialize()

    def setup_debug_images(self) -> None:
        images = [
            Image.open(self.path / "pifinder_debug_01.png"),  # Solves, brighter sky
            Image.open(self.path / "pifinder_debug_02.png"),  # Solves, darker sky
            Image.open(self.path / "empty.png"),  # Doesn't solve (no stars)
        ]
        self.images = list(zip(range(1, len(images) + 1), images))
        self.image_cycle = cycle(self.images)
        self.last_image_time: float = time.time()
        self.current_image_num, self.last_image = self.images[0]

    def initialize(self) -> None:
        self._camera_started = True

    def start_camera(self) -> None:
        self._camera_started = True

    def stop_camera(self) -> None:
        self._camera_started = False

    def capture(self) -> Image.Image:
        # Sleep for exposure time
        sleep_time = self.exposure_time / 1000000
        time.sleep(sleep_time)

        elapsed = time.time() - self.last_image_time
        # Swap every x seconds
        if elapsed > 10:
            self.current_image_num, self.last_image = next(self.image_cycle)
            logger.debug(
                f"Debug camera switched to test image #{self.current_image_num}"
            )
            self.last_image_time = time.time()
        return self.last_image

    def capture_bias(self):
        """Return black frame (bias capture not active)."""
        return Image.new("L", (512, 512), 0)

    def capture_file(self, filename) -> None:
        logger.warn("capture_file not implemented in Camera Debug")
        pass

    def capture_raw_file(self, filename) -> None:
        logger.warn("capture_raw_file not implemented in Camera Debug")
        pass

    def set_camera_config(
        self, exposure_time: float, gain: float
    ) -> Tuple[float, float]:
        logger.info(
            f"Setting debug camera config - Exposure: {exposure_time}µs, Gain: {gain}x"
        )
        self.exposure_time = exposure_time
        self.gain = gain
        return exposure_time, gain

    def get_cam_type(self) -> str:
        return self.camType

    def optical_train_known(self) -> bool:
        """No. These frames are a recording, not a view through this device.

        Whatever lens config states is a claim about glass that is not in the
        loop, so pairing it with the sensor above produces a field of view
        that describes nothing. Saying so is what keeps `--camera debug`
        solving whatever the config happens to hold -- including frames a
        developer drops into test_images/ from another train entirely, which
        no derived gate could have anticipated.
        """
        return False


def get_images(shared_state, camera_image, command_queue, console_queue, log_queue):
    """
    Instantiates the camera hardware
    then calls the universal image loop
    """
    MultiprocLogging.configurer(log_queue)
    cfg = config.Config()
    exposure_time = cfg.get_option("camera_exp")

    # Handle auto-exposure mode: use default value, auto-exposure will adjust
    if exposure_time == "auto":
        exposure_time = 400000  # Start with default 400ms

    camera_hardware = CameraDebug(exposure_time)
    camera_hardware.get_image_loop(
        shared_state, camera_image, command_queue, console_queue, cfg
    )
