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
from PiFinder import state_utils
from typing import Tuple
import logging
from PiFinder import utils

logger = logging.getLogger("Camera.Interface")


class CameraInterface:
    """The CameraInterface interface."""

    def initialize(self) -> None:
        pass

    def capture(self) -> Image.Image:
        return Image.Image()

    def capture_file(self, filename) -> None:
        pass

    def set_camera_config(
        self, exposure_time: float, gain: float
    ) -> Tuple[float, float]:
        return (0, 0)

    def get_cam_type(self) -> str:
        return "foo"

    def get_image_loop(
        self, shared_state, camera_image, command_queue, console_queue, cfg
    ):
        try:
            debug = False

            screen_direction = cfg.get_option("screen_direction")
            camera_rotation = cfg.get_option("camera_rotation")

            # Set path for test images
            root_dir = os.path.realpath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            test_image_path = os.path.join(
                root_dir, "test_images", "pifinder_debug_02.png"
            )

            # 60 half-second cycles
            sleep_delay = 60
            while True:
                sleeping = state_utils.sleep_for_framerate(
                    shared_state, limit_framerate=False
                )
                if sleeping:
                    # Even in sleep mode, we want to take photos every
                    # so often to update positions
                    sleep_delay -= 1
                    if sleep_delay > 0:
                        continue
                    else:
                        sleep_delay = 60

                imu_start = shared_state.imu()
                image_start_time = time.time()
                if not debug:
                    base_image = self.capture()
                    base_image = base_image.convert("L")
                    if camera_rotation is None:
                        if (
                            screen_direction == "right"
                            or screen_direction == "straight"
                            or screen_direction == "flat3"
                        ):
                            base_image = base_image.rotate(90)
                        else:
                            base_image = base_image.rotate(270)
                    else:
                        base_image = base_image.rotate(int(camera_rotation) * -1)
                else:
                    # load image and wait
                    base_image = Image.open(test_image_path)
                    time.sleep(1)
                image_end_time = time.time()
                # check imu to make sure we're still static
                imu_end = shared_state.imu()

                # see if we moved during exposure
                reading_diff = 0
                if imu_start and imu_end:
                    reading_diff = (
                        abs(imu_start["pos"][0] - imu_end["pos"][0])
                        + abs(imu_start["pos"][1] - imu_end["pos"][1])
                        + abs(imu_start["pos"][2] - imu_end["pos"][2])
                    )

                camera_image.paste(base_image)
                shared_state.set_last_image_metadata(
                    {
                        "exposure_start": image_start_time,
                        "exposure_end": image_end_time,
                        "imu": imu_end,
                        "imu_delta": reading_diff,
                    }
                )

                # Loop over any pending commands
                # There may be more than one!
                command = True
                while command:
                    try:
                        command = command_queue.get(block=False)
                    except queue.Empty:
                        command = ""

                    if command == "debug":
                        if debug:
                            debug = False
                        else:
                            debug = True

                    if command.startswith("set_exp"):
                        self.exposure_time = int(command.split(":")[1])
                        self.set_camera_config(self.exposure_time, self.gain)
                        console_queue.put("CAM: Exp=" + str(self.exposure_time))

                    if command.startswith("set_gain"):
                        self.gain = int(command.split(":")[1])
                        self.exposure_time, self.gain = self.set_camera_config(
                            self.exposure_time, self.gain
                        )
                        console_queue.put("CAM: Gain=" + str(self.gain))

                    if command == "exp_up" or command == "exp_dn":
                        if command == "exp_up":
                            self.exposure_time = int(self.exposure_time * 1.25)
                        else:
                            self.exposure_time = int(self.exposure_time * 0.75)
                        self.set_camera_config(self.exposure_time, self.gain)
                        console_queue.put("CAM: Exp=" + str(self.exposure_time))
                    if command == "exp_save":
                        console_queue.put("CAM: Exp Saved")
                        cfg.set_option("camera_exp", self.exposure_time)
                        cfg.set_option("camera_gain", int(self.gain))

                    if command.startswith("save"):
                        filename = command.split(":")[1]
                        filename = f"{utils.data_dir}/captures/{filename}.png"
                        self.capture_file(filename)
                        console_queue.put("CAM: Saved Image")
        except (BrokenPipeError, EOFError, FileNotFoundError):
            logger.exception("Error in Camera Loop")
