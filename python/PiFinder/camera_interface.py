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
from PiFinder import state_utils, utils
from PiFinder.auto_exposure import ExposurePIDController
from typing import Tuple, Optional
import logging

logger = logging.getLogger("Camera.Interface")


class CameraInterface:
    """The CameraInterface interface."""

    _camera_started = False
    _auto_exposure_enabled = False
    _auto_exposure_pid: Optional[ExposurePIDController] = None
    _last_solve_time: Optional[float] = None

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

    def start_camera(self) -> None:
        pass

    def stop_camera(self) -> None:
        pass

    def get_image_loop(
        self, shared_state, camera_image, command_queue, console_queue, cfg
    ):
        try:
            debug = False

            # Check if auto-exposure was previously enabled in config
            config_exp = cfg.get_option("camera_exp")
            if config_exp == "auto":
                self._auto_exposure_enabled = True
                self._last_solve_time = None
                if self._auto_exposure_pid is None:
                    self._auto_exposure_pid = ExposurePIDController()
                else:
                    self._auto_exposure_pid.reset()
                logger.info("Auto-exposure mode enabled from config")

            screen_direction = cfg.get_option("screen_direction")
            camera_rotation = cfg.get_option("camera_rotation")

            # Set path for test mode image
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
                if self._camera_started:
                    if not debug:
                        base_image = self.capture()
                        base_image = base_image.convert("L")
                        rotate_amount = 0
                        if camera_rotation is None:
                            if screen_direction in [
                                "right",
                                "straight",
                                "flat3",
                            ]:
                                rotate_amount = 90
                            elif screen_direction == "as_bloom":
                                rotate_amount = 90  # Specific rotation for AS Bloom
                            else:
                                rotate_amount = 270
                        else:
                            base_image = base_image.rotate(int(camera_rotation) * -1)

                        base_image = base_image.rotate(rotate_amount)
                    else:
                        # Test Mode: load image from disc and wait
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
                    image_metadata = {
                        "exposure_start": image_start_time,
                        "exposure_end": image_end_time,
                        "imu": imu_end,
                        "imu_delta": reading_diff,
                        "exposure_time": self.exposure_time,
                        "gain": self.gain,
                    }
                    shared_state.set_last_image_metadata(image_metadata)

                    # Auto-exposure: adjust based on plate solve results
                    # Updates as fast as new solve results arrive (naturally rate-limited)
                    if self._auto_exposure_enabled and self._auto_exposure_pid:
                        solution = shared_state.solution()
                        solve_source = solution.get("solve_source") if solution else None

                        # Handle camera solves (successful or failed)
                        if solve_source in ("CAM", "CAM_FAILED"):
                            matched_stars = solution.get("Matches", 0)
                            solve_attempt_time = solution.get("last_solve_attempt")
                            solve_rmse = solution.get("RMSE", 0)

                            # Only update on NEW solve results (not re-processing same solution)
                            # Use last_solve_attempt since it's set for both success and failure
                            if solve_attempt_time and solve_attempt_time != self._last_solve_time:
                                logger.info(
                                    f"Auto-exposure feedback - Stars: {matched_stars}, "
                                    f"RMSE: {solve_rmse:.1f}, Current exposure: {self.exposure_time}µs"
                                )

                                # Call PID update (now handles zero stars with recovery mode)
                                new_exposure = self._auto_exposure_pid.update(
                                    matched_stars, self.exposure_time
                                )

                                if new_exposure is not None and new_exposure != self.exposure_time:
                                    # Exposure value actually changed - update camera
                                    logger.info(
                                        f"Auto-exposure adjustment: {matched_stars} stars → "
                                        f"{self.exposure_time}µs → {new_exposure}µs "
                                        f"(change: {new_exposure - self.exposure_time:+d}µs)"
                                    )
                                    self.exposure_time = new_exposure
                                    self.set_camera_config(self.exposure_time, self.gain)
                                elif new_exposure is None:
                                    logger.debug(
                                        f"Auto-exposure: {matched_stars} stars, no adjustment needed"
                                    )
                                self._last_solve_time = solve_attempt_time

                # Loop over any pending commands
                # There may be more than one!
                command = True
                while command:
                    try:
                        command = command_queue.get(block=True, timeout=0.1)
                    except queue.Empty:
                        command = ""
                        continue
                    except Exception as e:
                        logger.error(f"CameraInterface: Command error: {e}")

                    try:
                        if command == "debug":
                            if debug:
                                debug = False
                            else:
                                debug = True

                        if command.startswith("set_exp"):
                            exp_value = command.split(":")[1]
                            if exp_value == "auto":
                                # Enable auto-exposure mode
                                self._auto_exposure_enabled = True
                                self._last_solve_time = None  # Reset solve tracking
                                if self._auto_exposure_pid is None:
                                    self._auto_exposure_pid = ExposurePIDController()
                                else:
                                    self._auto_exposure_pid.reset()
                                console_queue.put("CAM: Auto-Exposure Enabled")
                                logger.info("Auto-exposure mode enabled")
                            else:
                                # Disable auto-exposure and set manual exposure
                                self._auto_exposure_enabled = False
                                self.exposure_time = int(exp_value)
                                self.set_camera_config(self.exposure_time, self.gain)
                                # Update config to reflect manual exposure value
                                cfg.set_option("camera_exp", self.exposure_time)
                                console_queue.put("CAM: Exp=" + str(self.exposure_time))
                                logger.info(f"Manual exposure set: {self.exposure_time}µs")

                        if command.startswith("set_gain"):
                            old_gain = self.gain
                            self.gain = int(command.split(":")[1])
                            self.exposure_time, self.gain = self.set_camera_config(
                                self.exposure_time, self.gain
                            )
                            console_queue.put("CAM: Gain=" + str(self.gain))
                            logger.info(f"Gain changed: {old_gain}x → {self.gain}x")

                        if command == "exp_up" or command == "exp_dn":
                            # Manual exposure adjustments disable auto-exposure
                            self._auto_exposure_enabled = False
                            if command == "exp_up":
                                self.exposure_time = int(self.exposure_time * 1.25)
                            else:
                                self.exposure_time = int(self.exposure_time * 0.75)
                            self.set_camera_config(self.exposure_time, self.gain)
                            console_queue.put("CAM: Exp=" + str(self.exposure_time))
                        if command == "exp_save":
                            # Saving exposure disables auto-exposure and locks to current value
                            self._auto_exposure_enabled = False
                            cfg.set_option("camera_exp", self.exposure_time)
                            cfg.set_option("camera_gain", int(self.gain))
                            console_queue.put(f"CAM: Exp Saved ({self.exposure_time}µs)")
                            logger.info(f"Exposure saved and auto-exposure disabled: {self.exposure_time}µs")

                        if command.startswith("save"):
                            filename = command.split(":")[1]
                            filename = f"{utils.data_dir}/captures/{filename}.png"
                            self.capture_file(filename)
                            console_queue.put("CAM: Saved Image")
                        if command.startswith("stop"):
                            self.stop_camera()
                            console_queue.put("CAM: Stopped camera")
                        if command.startswith("start"):
                            self.start_camera()
                            console_queue.put("CAM: Started camera")
                    except ValueError as e:
                        logger.error(
                            f"Error processing camera command '{command}': {str(e)}"
                        )
                        console_queue.put(
                            f"CAM ERROR: Invalid command format - {str(e)}"
                        )
                    except AttributeError as e:
                        logger.error(
                            f"Camera component not initialized for command '{command}': {str(e)}"
                        )
                        console_queue.put("CAM ERROR: Camera not properly initialized")
                    except Exception as e:
                        logger.error(
                            f"Unexpected error processing camera command '{command}': {str(e)}"
                        )
                        console_queue.put(f"CAM ERROR: {str(e)}")
            logger.info(
                f"CameraInterface: Camera loop exited with command: '{command}'"
            )
        except (BrokenPipeError, EOFError, FileNotFoundError):
            logger.exception("Error in Camera Loop")
