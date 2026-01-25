#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the camera
* Captures images
* Places preview images in queue
* Places solver images in queue
* Takes full res images on demand

"""

import datetime
import logging
import os
import queue
import time
from typing import Tuple, Optional

from PIL import Image

from PiFinder import state_utils, utils
from PiFinder.auto_exposure import (
    ExposurePIDController,
    ExposureSNRController,
    SweepZeroStarHandler,
    ExponentialSweepZeroStarHandler,
    ResetZeroStarHandler,
    HistogramZeroStarHandler,
    generate_exposure_sweep,
)
from PiFinder.sqm.camera_profiles import detect_camera_type

logger = logging.getLogger("Camera.Interface")


class CameraInterface:
    """The CameraInterface interface."""

    _camera_started = False
    _save_next_to = None  # Filename to save next capture to (None = don't save)
    _auto_exposure_enabled = False
    _auto_exposure_mode = "pid"  # "pid" or "snr"
    _auto_exposure_pid: Optional[ExposurePIDController] = None
    _auto_exposure_snr: Optional[ExposureSNRController] = None
    _last_solve_time: Optional[float] = None

    def initialize(self) -> None:
        pass

    def capture(self) -> Image.Image:
        return Image.Image()

    def capture_file(self, filename) -> None:
        pass

    def capture_raw_file(self, filename) -> None:
        pass

    def capture_bias(self):
        """
        Capture a bias frame for pedestal calculation.
        Base implementation returns a black frame (no bias correction).
        Override in subclasses that support bias frames.
        Returns Image.Image or np.ndarray depending on implementation.
        """
        return Image.new("L", (512, 512), 0)  # Black 512x512 image

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
            # Store shared_state for access by capture() methods
            self.shared_state = shared_state

            # Store camera type in shared state for SQM calibration
            camera_type_str = self.get_cam_type()  # e.g., "PI imx296", "PI hq"
            if " " in camera_type_str:
                # Extract just the sensor type (imx296, hq, imx462, etc.)
                camera_type = camera_type_str.split(" ")[1].lower()
                shared_state.set_camera_type(camera_type)
                logger.info(f"Camera type set to: {camera_type}")

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

            # 60 half-second cycles (30 seconds between captures in sleep mode)
            sleep_delay = 60
            was_sleeping = False
            while True:
                sleeping = state_utils.sleep_for_framerate(
                    shared_state, limit_framerate=False
                )
                if sleeping:
                    # Log transition to sleep mode
                    if not was_sleeping:
                        logger.info("Camera entering low-power sleep mode")
                        was_sleeping = True
                    # Even in sleep mode, we want to take photos every
                    # so often to update positions
                    sleep_delay -= 1
                    if sleep_delay > 0:
                        continue
                    else:
                        sleep_delay = 60
                        logger.debug("Sleep mode: waking for periodic capture")
                elif was_sleeping:
                    logger.info("Camera exiting low-power sleep mode")
                    was_sleeping = False

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
                        base_image = base_image.convert(
                            "L"
                        )  # Convert to grayscale to match camera output
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
                        solve_source = (
                            solution.get("solve_source") if solution else None
                        )

                        # Handle camera solves (successful or failed)
                        if solve_source in ("CAM", "CAM_FAILED"):
                            matched_stars = solution.get("Matches", 0)
                            solve_attempt_time = solution.get("last_solve_attempt")
                            solve_rmse = solution.get("RMSE")

                            # Only update on NEW solve results (not re-processing same solution)
                            # Use last_solve_attempt since it's set for both success and failure
                            if (
                                solve_attempt_time
                                and solve_attempt_time != self._last_solve_time
                            ):
                                rmse_str = (
                                    f"{solve_rmse:.1f}"
                                    if solve_rmse is not None
                                    else "N/A"
                                )
                                logger.debug(
                                    f"Auto-exposure feedback - Stars: {matched_stars}, "
                                    f"RMSE: {rmse_str}, Current exposure: {self.exposure_time}µs"
                                )

                                # Call auto-exposure update based on current mode
                                if self._auto_exposure_mode == "snr":
                                    # SNR mode: use background-based controller (for SQM measurements)
                                    if self._auto_exposure_snr is None:
                                        # Use camera profile to derive thresholds
                                        try:
                                            cam_type = detect_camera_type(self.get_cam_type())
                                            cam_type = f"{cam_type}_processed"
                                            self._auto_exposure_snr = (
                                                ExposureSNRController.from_camera_profile(cam_type)
                                            )
                                        except ValueError as e:
                                            # Unknown camera, use defaults
                                            logger.warning(
                                                f"Camera detection failed: {e}, using default SNR thresholds"
                                            )
                                            self._auto_exposure_snr = ExposureSNRController()
                                    # Get adaptive noise floor from shared state
                                    adaptive_noise_floor = self.shared_state.noise_floor()
                                    new_exposure = self._auto_exposure_snr.update(
                                        self.exposure_time, base_image,
                                        noise_floor=adaptive_noise_floor
                                    )
                                else:
                                    # PID mode: use star-count based controller (default)
                                    # Pass base_image for histogram analysis in zero-star handler
                                    new_exposure = self._auto_exposure_pid.update(
                                        matched_stars, self.exposure_time, base_image
                                    )

                                if (
                                    new_exposure is not None
                                    and new_exposure != self.exposure_time
                                ):
                                    # Exposure value actually changed - update camera
                                    logger.info(
                                        f"Auto-exposure adjustment: {matched_stars} stars → "
                                        f"{self.exposure_time}µs → {new_exposure}µs "
                                        f"(change: {new_exposure - self.exposure_time:+d}µs)"
                                    )
                                    self.exposure_time = new_exposure
                                    self.set_camera_config(
                                        self.exposure_time, self.gain
                                    )
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
                                logger.info(
                                    f"Manual exposure set: {self.exposure_time}µs"
                                )

                        if command.startswith("set_gain"):
                            old_gain = self.gain
                            self.gain = int(command.split(":")[1])
                            self.exposure_time, self.gain = self.set_camera_config(
                                self.exposure_time, self.gain
                            )
                            console_queue.put("CAM: Gain=" + str(self.gain))
                            logger.info(f"Gain changed: {old_gain}x → {self.gain}x")

                        if command.startswith("set_ae_handler"):
                            handler_type = command.split(":")[1]
                            if self._auto_exposure_pid is not None:
                                new_handler = None
                                if handler_type == "sweep":
                                    new_handler = SweepZeroStarHandler(
                                        min_exposure=self._auto_exposure_pid.min_exposure,
                                        max_exposure=self._auto_exposure_pid.max_exposure,
                                    )
                                elif handler_type == "exponential":
                                    new_handler = ExponentialSweepZeroStarHandler(
                                        min_exposure=self._auto_exposure_pid.min_exposure,
                                        max_exposure=self._auto_exposure_pid.max_exposure,
                                    )
                                elif handler_type == "reset":
                                    new_handler = ResetZeroStarHandler(
                                        reset_exposure=400000  # 0.4s
                                    )
                                elif handler_type == "histogram":
                                    new_handler = HistogramZeroStarHandler(
                                        min_exposure=self._auto_exposure_pid.min_exposure,
                                        max_exposure=self._auto_exposure_pid.max_exposure,
                                    )
                                else:
                                    logger.warning(
                                        f"Unknown zero-star handler type: {handler_type}"
                                    )

                                if new_handler is not None:
                                    self._auto_exposure_pid._zero_star_handler = (
                                        new_handler
                                    )
                                    console_queue.put(f"CAM: AE Handler={handler_type}")
                                    logger.info(
                                        f"Auto-exposure zero-star handler changed to: {handler_type}"
                                    )
                            else:
                                logger.warning(
                                    "Cannot set AE handler: auto-exposure not initialized"
                                )

                        if command.startswith("set_ae_mode"):
                            mode = command.split(":")[1]
                            if mode in ["pid", "snr"]:
                                self._auto_exposure_mode = mode
                                console_queue.put(f"CAM: AE Mode={mode.upper()}")
                                logger.info(
                                    f"Auto-exposure mode changed to: {mode.upper()}"
                                )
                            else:
                                logger.warning(
                                    f"Unknown auto-exposure mode: {mode} (valid: pid, snr)"
                                )

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
                            console_queue.put(
                                f"CAM: Exp Saved ({self.exposure_time}µs)"
                            )
                            logger.info(
                                f"Exposure saved and auto-exposure disabled: {self.exposure_time}µs"
                            )

                        if command.startswith("save"):
                            # Set flag to save next capture to this file
                            self._save_next_to = command.split(":")[1]
                            console_queue.put("CAM: Save flag set")

                        if (
                            command.startswith("capture")
                            and command != "capture_exp_sweep"
                        ):
                            # Capture single frame and update shared state
                            # This is used by SQM calibration for precise exposure control
                            captured_image = self.capture()
                            camera_image.paste(captured_image)

                            # If save flag is set, save to disk
                            if self._save_next_to:
                                # Build full path
                                filename = (
                                    f"{utils.data_dir}/captures/{self._save_next_to}"
                                )
                                if not filename.endswith(".png"):
                                    filename += ".png"
                                self.capture_file(filename)

                                # Also save raw as TIFF
                                raw_filename = filename.replace(".png", ".tiff")
                                if not raw_filename.endswith(".tiff"):
                                    raw_filename += ".tiff"
                                self.capture_raw_file(raw_filename)

                                console_queue.put("CAM: Captured + Saved")
                                self._save_next_to = None  # Clear flag
                            else:
                                console_queue.put("CAM: Captured")

                        if command.startswith("capture_exp_sweep"):
                            # Capture exposure sweep - save both RAW and processed images
                            # at different exposures for SQM testing
                            # RAW: 16-bit TIFF to preserve full sensor bit depth
                            # Processed: 8-bit PNG from normal camera.capture() pipeline

                            # Parse reference SQM if provided
                            reference_sqm = None
                            if ":" in command:
                                try:
                                    reference_sqm = float(command.split(":")[1])
                                    logger.info(f"Reference SQM: {reference_sqm:.2f}")
                                except (ValueError, IndexError):
                                    logger.warning("Invalid reference SQM in command")

                            logger.info(
                                "Starting exposure sweep capture (100 image pairs)"
                            )
                            console_queue.put("CAM: Starting sweep...")

                            # Save current settings
                            original_exposure = self.exposure_time
                            original_gain = self.gain
                            original_ae_enabled = self._auto_exposure_enabled

                            # Disable auto-exposure during sweep
                            self._auto_exposure_enabled = False

                            # Generate 20 exposure values with logarithmic spacing
                            # from 25ms (25000µs) to 1s (1000000µs)
                            min_exp = 25000  # 25ms
                            max_exp = 1000000  # 1s
                            num_images = 20

                            # Generate logarithmic sweep using shared utility
                            sweep_exposures = generate_exposure_sweep(
                                min_exp, max_exp, num_images
                            )

                            # Generate timestamp for this sweep session using GPS time
                            gps_time = shared_state.datetime()
                            if gps_time:
                                timestamp = gps_time.strftime("%Y%m%d_%H%M%S")
                            else:
                                # Fallback to Pi time if GPS not available
                                timestamp = datetime.datetime.now().strftime(
                                    "%Y%m%d_%H%M%S"
                                )
                                logger.warning(
                                    "GPS time not available, using Pi system time for sweep directory name"
                                )

                            # Create sweep directory
                            from pathlib import Path

                            sweep_dir = Path(
                                f"{utils.data_dir}/captures/sweep_{timestamp}"
                            )
                            sweep_dir.mkdir(parents=True, exist_ok=True)

                            logger.info(f"Saving sweep to: {sweep_dir}")
                            console_queue.put("CAM: Starting sweep...")

                            for i, exp_us in enumerate(sweep_exposures, 1):
                                # Update progress at start of each capture
                                console_queue.put(f"CAM: Sweep {i}/{num_images}")

                                # Set exposure
                                self.exposure_time = exp_us
                                self.set_camera_config(self.exposure_time, self.gain)

                                # Flush camera buffer - discard pre-buffered frames with old exposure
                                # Picamera2 maintains a frame queue, need to flush frames captured
                                # before the new exposure setting was applied
                                logger.debug(
                                    f"Flushing camera buffer for {exp_us}µs exposure"
                                )
                                _ = self.capture()  # Discard buffered frame 1
                                _ = self.capture()  # Discard buffered frame 2

                                # Now capture both processed and RAW images with correct exposure
                                exp_ms = exp_us / 1000

                                # Save processed 8-bit PNG (same as production capture() method)
                                processed_filename = (
                                    sweep_dir
                                    / f"img_{i:03d}_{exp_ms:.2f}ms_processed.png"
                                )
                                processed_img = (
                                    self.capture()
                                )  # Returns 8-bit PIL Image
                                processed_img.save(str(processed_filename))

                                # Save RAW TIFF (16-bit, from camera.capture_raw_file())
                                raw_filename = (
                                    sweep_dir / f"img_{i:03d}_{exp_ms:.2f}ms_raw.tiff"
                                )
                                self.capture_raw_file(str(raw_filename))

                                logger.debug(
                                    f"Captured sweep images {i}/{num_images}: {exp_ms:.2f}ms (PNG+TIFF)"
                                )

                            # Restore original settings
                            self.exposure_time = original_exposure
                            self.gain = original_gain
                            self._auto_exposure_enabled = original_ae_enabled
                            self.set_camera_config(self.exposure_time, self.gain)

                            # Save sweep metadata (GPS time, location, altitude)
                            logger.info("Starting sweep metadata save...")
                            try:
                                from PiFinder.sqm.save_sweep_metadata import (
                                    save_sweep_metadata,
                                )

                                # Get GPS datetime (not Pi time)
                                gps_datetime = shared_state.datetime()
                                logger.debug(f"GPS datetime: {gps_datetime}")

                                # Get observer location
                                location = shared_state.location()
                                logger.debug(
                                    f"Location: lat={location.lat}, lon={location.lon}, alt={location.altitude}"
                                )

                                # Get current solve with RA/Dec/Alt/Az
                                solve_state = shared_state.solution()
                                ra_deg = None
                                dec_deg = None
                                altitude_deg = None
                                azimuth_deg = None

                                if solve_state is not None:
                                    ra_deg = solve_state.get("RA")
                                    dec_deg = solve_state.get("Dec")
                                    altitude_deg = solve_state.get("Alt")
                                    azimuth_deg = solve_state.get("Az")
                                    logger.debug(
                                        f"Solve: RA={ra_deg}, Dec={dec_deg}, Alt={altitude_deg}, Az={azimuth_deg}"
                                    )

                                # Save metadata
                                logger.info(
                                    f"Calling save_sweep_metadata for {sweep_dir}"
                                )
                                save_sweep_metadata(
                                    sweep_dir=sweep_dir,
                                    observer_lat=location.lat,
                                    observer_lon=location.lon,
                                    observer_altitude_m=location.altitude,
                                    gps_datetime=gps_datetime.isoformat()
                                    if gps_datetime
                                    else None,
                                    reference_sqm=reference_sqm,
                                    ra_deg=ra_deg,
                                    dec_deg=dec_deg,
                                    altitude_deg=altitude_deg,
                                    azimuth_deg=azimuth_deg,
                                    notes=f"Exposure sweep: {num_images} images, {min_exp/1000:.1f}-{max_exp/1000:.1f}ms",
                                )
                                logger.info(
                                    f"Successfully saved sweep metadata to {sweep_dir}/sweep_metadata.json"
                                )
                            except Exception as e:
                                logger.error(
                                    f"Failed to save sweep metadata: {e}", exc_info=True
                                )

                            console_queue.put("CAM: Sweep done!")
                            logger.info(
                                f"Exposure sweep completed: {num_images} image pairs in {sweep_dir}"
                            )

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
