#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
SQM Calibration Wizard

This module provides a step-by-step wizard for calibrating the SQM (Sky Quality Meter)
noise floor estimation. The calibration process:

1. Captures bias frames (0s exposure with lens cap on) to measure read noise
2. Captures dark frames (actual exposure with lens cap on) to measure dark current
3. Captures sky frames (actual exposure without cap) to measure actual sky brightness
4. Calculates noise parameters and updates the camera profile
5. Saves calibration data for future use

The wizard guides the user through lens cap placement and displays progress.
"""

import time
import os
import logging
import numpy as np
from enum import Enum
from typing import Optional, List

from PiFinder.ui.base import UIModule
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu

logger = logging.getLogger("PiFinder.SQMCalibration")


class CalibrationState(Enum):
    """Calibration wizard states"""

    INTRO = "intro"  # Introduction screen
    CAP_ON_INSTRUCTION = "cap_on"  # Instruction to put lens cap on
    CAPTURING_BIAS = "bias"  # Capturing bias frames (0s exposure)
    CAPTURING_DARK = "dark"  # Capturing dark frames (actual exposure)
    CAP_OFF_INSTRUCTION = "cap_off"  # Instruction to remove lens cap
    CAPTURING_SKY = "sky"  # Capturing sky frames with plate solving
    ANALYZING = "analyzing"  # Computing results
    RESULTS = "results"  # Showing final results
    ERROR = "error"  # Error occurred


class UISQMCalibration(UIModule):
    """
    SQM Calibration Wizard UI Module

    A multi-step wizard that guides the user through SQM calibration.
    """

    __title__ = "SQM CAL"
    __help_name__ = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Wizard state machine
        self.state = CalibrationState.INTRO
        self.error_message = ""

        # Calibration parameters
        self.num_frames = 10  # Number of frames to capture per measurement
        self.current_frame = 0  # Current frame being captured

        # Debug option: save calibration frames to disk
        self.save_frames_enabled = False
        self.calibration_output_dir = None  # Set when debug enabled

        # Marking menu for debug toggle
        self.marking_menu = self._create_marking_menu()

        # Separate storage for each frame type - PROCESSED (8-bit)
        self.bias_frames: List[np.ndarray] = []
        self.dark_frames: List[np.ndarray] = []
        self.sky_frames: List[np.ndarray] = []

        # Separate storage for each frame type - RAW (16-bit)
        self.bias_frames_raw: List[np.ndarray] = []
        self.dark_frames_raw: List[np.ndarray] = []
        self.sky_frames_raw: List[np.ndarray] = []

        # Store solution for each sky frame (needed for SQM calculation)
        self.sky_solutions: List[dict] = []

        # Calibration results - PROCESSED (8-bit)
        self.bias_offset: Optional[float] = None
        self.read_noise: Optional[float] = None
        self.dark_current_rate: Optional[float] = None
        self.sky_brightness: Optional[float] = None

        # Calibration results - RAW (16-bit)
        self.bias_offset_raw: Optional[float] = None
        self.read_noise_raw: Optional[float] = None
        self.dark_current_rate_raw: Optional[float] = None
        self.sky_brightness_raw: Optional[float] = None

        # SQM measurements from sky frames
        self.sqm_median: Optional[float] = None  # Median SQM from all sky frames
        self.sqm_values: List[float] = []  # Individual SQM values

        # Store original camera settings to restore later
        self.original_exposure = None
        self.original_gain = None
        self.original_ae_state = None

        # Exposure time will be set in active() based on current exposure
        # with minimum of 400ms to ensure good SNR
        self.exposure_time_us = None

        # Timeout tracking for sky frame capture
        self.sky_capture_start_time = None
        self.sky_capture_timeout = 30  # seconds - skip if no solve after this

    def active(self):
        """Called when module becomes active"""
        # Store original camera settings
        metadata = self.shared_state.last_image_metadata()
        self.original_exposure = metadata.get("exposure_time", 500000)

        # Use max(current_exposure, 400ms) to ensure good SNR
        # but preserve higher exposure if already set
        self.exposure_time_us = max(self.original_exposure, 400000)

        # Set exposure for calibration
        self.command_queues["camera"].put(f"set_exp:{self.exposure_time_us}")
        time.sleep(0.2)  # Wait for camera to apply setting

        # Start with intro screen
        self.state = CalibrationState.INTRO
        self.update(force=True)

    def inactive(self):
        """Called when module becomes inactive"""
        # Restore original camera settings
        if self.original_exposure is not None:
            self.command_queues["camera"].put(f"set_exp:{self.original_exposure}")
        else:
            # Fallback: re-enable auto-exposure
            self.command_queues["camera"].put("set_exp:auto")

    def update(self, force=False):
        """Update the display based on current state"""
        self.clear_screen()

        if self.state == CalibrationState.INTRO:
            self._draw_intro()
        elif self.state == CalibrationState.CAP_ON_INSTRUCTION:
            self._draw_cap_on_instruction()
        elif self.state == CalibrationState.CAPTURING_BIAS:
            self._draw_progress("BIAS", self.current_frame, self.num_frames)
            self._capture_bias_frame()
        elif self.state == CalibrationState.CAPTURING_DARK:
            self._draw_progress("DARK", self.current_frame, self.num_frames)
            self._capture_dark_frame()
        elif self.state == CalibrationState.CAP_OFF_INSTRUCTION:
            self._draw_cap_off_instruction()
        elif self.state == CalibrationState.CAPTURING_SKY:
            self._draw_progress("SKY", self.current_frame, self.num_frames)
            self._capture_sky_frame()
        elif self.state == CalibrationState.ANALYZING:
            self._draw_analyzing()
            self._analyze_calibration()
        elif self.state == CalibrationState.RESULTS:
            self._draw_results()
        elif self.state == CalibrationState.ERROR:
            self._draw_error()

        return self.screen_update(title_bar=True)

    # ============================================
    # Drawing methods for each state
    # ============================================

    def _draw_intro(self):
        """Draw introduction screen"""
        self.draw.text(
            (10, 20),
            "SQM CAL",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        lines = [
            "Measure noise floor",
            "",
            "Need:",
            "• Lens cap",
            "• ~3 minutes",
        ]

        y = 40
        for line in lines:
            self.draw.text(
                (10, y), line, font=self.fonts.base.font, fill=self.colors.get(192)
            )
            y += self.fonts.base.height + 2

        # Legend
        self.draw.text(
            (10, 110),
            f"{self._SQUARE_} START  0 CANCEL",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    def _draw_cap_on_instruction(self):
        """Draw lens cap on instruction"""
        self.draw.text(
            (10, 30),
            "PUT LENS CAP ON",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        self.draw.text(
            (10, 50),
            "Cover the camera",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )
        self.draw.text(
            (10, 62),
            "lens completely to",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )
        self.draw.text(
            (10, 74),
            "block all light.",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

        # Legend
        self.draw.text(
            (10, 110),
            f"{self._SQUARE_} READY  0 CANCEL",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    def _draw_cap_off_instruction(self):
        """Draw lens cap off instruction"""
        self.draw.text(
            (10, 30),
            "REMOVE LENS CAP",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        self.draw.text(
            (10, 50),
            "Remove the cap and",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )
        self.draw.text(
            (10, 62),
            "point at dark sky.",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )
        self.draw.text(
            (10, 74),
            "Wait for solve.",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

        # Legend
        self.draw.text(
            (10, 110),
            f"{self._SQUARE_} READY  0 CANCEL",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    def _draw_progress(self, label: str, current: int, total: int):
        """Draw progress bar for frame capture"""
        self.draw.text(
            (10, 20),
            f"{label} FRAMES",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        # Progress text
        self.draw.text(
            (10, 40),
            f"{current} / {total}",
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )

        # Progress bar
        bar_x = 10
        bar_y = 70
        bar_width = 108
        bar_height = 12

        # Background
        self.draw.rectangle(
            [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
            outline=self.colors.get(128),
            fill=self.colors.get(0),
        )

        # Filled portion
        if total > 0:
            filled_width = int(bar_width * (current / total))
            self.draw.rectangle(
                [bar_x, bar_y, bar_x + filled_width, bar_y + bar_height],
                fill=self.colors.get(128),
            )

        # Show different message for sky frames (which need plate solve)
        if label == "SKY":
            # Show timeout countdown if waiting for solve
            if self.sky_capture_start_time is not None and current == 0:
                elapsed = time.time() - self.sky_capture_start_time
                remaining = int(self.sky_capture_timeout - elapsed)
                if remaining > 0:
                    self.draw.text(
                        (10, 90),
                        f"Wait for solve: {remaining}s",
                        font=self.fonts.base.font,
                        fill=self.colors.get(128),
                    )
                else:
                    self.draw.text(
                        (10, 90),
                        "No solve detected",
                        font=self.fonts.base.font,
                        fill=self.colors.get(128),
                    )
            else:
                self.draw.text(
                    (10, 90),
                    "Hold steady...",
                    font=self.fonts.base.font,
                    fill=self.colors.get(64),
                )
            # Show skip option
            self.draw.text(
                (10, 110),
                "0: SKIP SKY",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
        else:
            self.draw.text(
                (10, 90),
                "Hold steady...",
                font=self.fonts.base.font,
                fill=self.colors.get(64),
            )

    def _draw_analyzing(self):
        """Draw analyzing screen"""
        self.draw.text(
            (10, 40),
            "ANALYZING...",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        self.draw.text(
            (10, 60),
            "Computing noise",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        self.draw.text(
            (10, 72),
            "parameters...",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )

    def _draw_results(self):
        """Draw final results - both processed and raw"""
        self.draw.text(
            (10, 18),
            "CAL COMPLETE",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        y = 36

        # Header row
        self.draw.text(
            (10, y),
            "       8-bit   16-bit",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        y += self.fonts.base.height + 2

        # Bias offset
        if self.bias_offset is not None and self.bias_offset_raw is not None:
            self.draw.text(
                (10, y),
                f"Bias: {self.bias_offset:4.1f}  {self.bias_offset_raw:6.1f}",
                font=self.fonts.base.font,
                fill=self.colors.get(192),
            )
            y += self.fonts.base.height + 2

        # Read noise
        if self.read_noise is not None and self.read_noise_raw is not None:
            self.draw.text(
                (10, y),
                f"Read: {self.read_noise:4.2f}  {self.read_noise_raw:6.2f}",
                font=self.fonts.base.font,
                fill=self.colors.get(192),
            )
            y += self.fonts.base.height + 2

        # Dark current
        if (
            self.dark_current_rate is not None
            and self.dark_current_rate_raw is not None
        ):
            self.draw.text(
                (10, y),
                f"Dark: {self.dark_current_rate:4.2f}  {self.dark_current_rate_raw:6.2f}",
                font=self.fonts.base.font,
                fill=self.colors.get(192),
            )
            y += self.fonts.base.height + 2

        # SQM median result
        y += 2  # Extra spacing before SQM
        if self.sqm_median is not None:
            self.draw.text(
                (10, y),
                f"SQM: {self.sqm_median:.2f}",
                font=self.fonts.base.font,
                fill=self.colors.get(255),  # Brighter for emphasis
            )
        else:
            self.draw.text(
                (10, y),
                "SQM: N/A",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )

        # Legend
        self.draw.text(
            (10, 110),
            f"{self._SQUARE_} DONE",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    def _draw_error(self):
        """Draw error screen"""
        self.draw.text(
            (10, 30),
            "ERROR",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        # Wrap error message
        y = 50
        words = self.error_message.split()
        line = ""
        for word in words:
            test_line = line + " " + word if line else word
            if len(test_line) <= 18:  # Rough character limit
                line = test_line
            else:
                self.draw.text(
                    (10, y), line, font=self.fonts.base.font, fill=self.colors.get(192)
                )
                y += self.fonts.base.height + 2
                line = word

        if line:
            self.draw.text(
                (10, y), line, font=self.fonts.base.font, fill=self.colors.get(192)
            )

        # Legend
        self.draw.text(
            (10, 110),
            f"{self._SQUARE_} EXIT",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    # ============================================
    # Frame capture methods
    # ============================================

    def _capture_bias_frame(self):
        """Capture a bias frame (0s exposure) - both processed and raw"""
        if self.current_frame == 0:
            # First frame: set exposure to minimum (closest to 0)
            self.command_queues["camera"].put("set_exp:1")  # Minimum exposure
            time.sleep(0.2)  # Wait for camera to apply setting
            self.bias_frames = []
            self.bias_frames_raw = []

        # Set save flag if debug enabled, then capture
        if self.save_frames_enabled:
            filename = os.path.join(
                self.calibration_output_dir, f"bias_{self.current_frame:03d}.png"
            )
            self.command_queues["camera"].put(f"save:{filename}")
        self.command_queues["camera"].put("capture")

        time.sleep(0.3)  # Wait for capture

        # Get PROCESSED image (8-bit) from shared memory
        img = self.camera_image.copy()
        img = img.convert(mode="L")
        np_image = np.asarray(img, dtype=np.uint8)
        self.bias_frames.append(np_image)

        # Get RAW image (16-bit) from shared state
        raw_array = self.shared_state.cam_raw()
        if raw_array is not None:
            self.bias_frames_raw.append(raw_array.copy())

        self.current_frame += 1

        if self.current_frame >= self.num_frames:
            # Done capturing bias frames
            self.state = CalibrationState.CAPTURING_DARK
            self.current_frame = 0
            # Restore original exposure for dark frames
            self.command_queues["camera"].put(f"set_exp:{self.exposure_time_us}")
            time.sleep(0.2)
        else:
            time.sleep(0.1)  # Small delay between frames

    def _capture_dark_frame(self):
        """Capture a dark frame (actual exposure with cap on) - both processed and raw"""
        if self.current_frame == 0:
            self.dark_frames = []
            self.dark_frames_raw = []

        # Set save flag if debug enabled, then capture
        if self.save_frames_enabled:
            filename = os.path.join(
                self.calibration_output_dir, f"dark_{self.current_frame:03d}.png"
            )
            self.command_queues["camera"].put(f"save:{filename}")
        self.command_queues["camera"].put("capture")

        time.sleep(0.3)  # Wait for capture

        # Get PROCESSED image (8-bit) from shared memory
        img = self.camera_image.copy()
        img = img.convert(mode="L")
        np_image = np.asarray(img, dtype=np.uint8)
        self.dark_frames.append(np_image)

        # Get RAW image (16-bit) from shared state
        raw_array = self.shared_state.cam_raw()
        if raw_array is not None:
            self.dark_frames_raw.append(raw_array.copy())

        self.current_frame += 1

        if self.current_frame >= self.num_frames:
            # Done capturing dark frames
            self.state = CalibrationState.CAP_OFF_INSTRUCTION
            self.current_frame = 0
        else:
            time.sleep(0.5)  # Wait for full exposure between frames

    def _capture_sky_frame(self):
        """Capture a sky frame (actual exposure, needs plate solve) - both processed and raw"""
        if self.current_frame == 0:
            self.sky_frames = []
            self.sky_frames_raw = []
            self.sky_solutions = []
            # Start timeout timer
            if self.sky_capture_start_time is None:
                self.sky_capture_start_time = time.time()

        # Check for timeout - if no solve after timeout, skip sky frames
        if self.sky_capture_start_time is not None:
            elapsed = time.time() - self.sky_capture_start_time
            if elapsed > self.sky_capture_timeout and self.current_frame == 0:
                logger.warning(
                    f"Sky frame capture timed out after {self.sky_capture_timeout}s - skipping to analysis"
                )
                # Skip to analyzing with no sky frames
                self.state = CalibrationState.ANALYZING
                self.current_frame = 0
                return

        # Check if we have a recent solve
        if not self.shared_state.solve_state():
            # No solve yet, wait
            time.sleep(0.1)
            return

        solution = self.shared_state.solution()
        if solution.get("RA") is None:
            # Invalid solve, wait
            time.sleep(0.1)
            return

        # Valid solve, set save flag if debug enabled, then capture
        if self.save_frames_enabled:
            filename = os.path.join(
                self.calibration_output_dir, f"sky_{self.current_frame:03d}.png"
            )
            self.command_queues["camera"].put(f"save:{filename}")
        self.command_queues["camera"].put("capture")

        time.sleep(0.3)  # Wait for capture

        # Get PROCESSED image (8-bit) from shared memory
        img = self.camera_image.copy()
        img = img.convert(mode="L")
        np_image = np.asarray(img, dtype=np.uint8)
        self.sky_frames.append(np_image)

        # Get RAW image (16-bit) from shared state
        raw_array = self.shared_state.cam_raw()
        if raw_array is not None:
            self.sky_frames_raw.append(raw_array.copy())

        # Store the solution for this frame (copy it so it doesn't change)
        self.sky_solutions.append(solution.copy())

        self.current_frame += 1

        if self.current_frame >= self.num_frames:
            # Done capturing sky frames
            self.state = CalibrationState.ANALYZING
            self.current_frame = 0
        else:
            time.sleep(0.5)  # Wait between frames

    # ============================================
    # Analysis methods
    # ============================================

    def _analyze_calibration(self):
        """Analyze captured frames and compute calibration parameters for BOTH processed and raw"""
        try:
            # This runs once, then moves to results
            if self.bias_offset is not None:
                # Already analyzed, show results
                self.state = CalibrationState.RESULTS
                return

            # Check that we have enough frames for BOTH processed and raw
            if len(self.bias_frames) < self.num_frames:
                self.error_message = f"Not enough bias frames ({len(self.bias_frames)})"
                self.state = CalibrationState.ERROR
                return

            if len(self.dark_frames) < self.num_frames:
                self.error_message = f"Not enough dark frames ({len(self.dark_frames)})"
                self.state = CalibrationState.ERROR
                return

            if len(self.bias_frames_raw) < self.num_frames:
                camera_type = self.shared_state.camera_type()
                if "Debug" in camera_type:
                    self.error_message = "Calibration not available with debug camera"
                else:
                    self.error_message = f"ERROR: {len(self.bias_frames_raw)}/{self.num_frames} raw bias frames captured"
                self.state = CalibrationState.ERROR
                return

            if len(self.dark_frames_raw) < self.num_frames:
                camera_type = self.shared_state.camera_type()
                if "Debug" in camera_type:
                    self.error_message = "Calibration not available with debug camera"
                else:
                    self.error_message = f"ERROR: {len(self.dark_frames_raw)}/{self.num_frames} raw dark frames captured"
                self.state = CalibrationState.ERROR
                return

            exposure_sec = self.exposure_time_us / 1_000_000.0

            # ========== PROCESSED (8-bit) CALIBRATION ==========

            # 1. Compute bias offset (median of all pixels in all bias frames)
            bias_stack = np.array(self.bias_frames, dtype=np.float32)
            self.bias_offset = float(np.median(bias_stack))

            # 2. Compute read noise using temporal variance (not spatial)
            # Spatial std includes fixed pattern noise (PRNU), which is wrong.
            # Temporal variance at each pixel measures true read noise.
            temporal_variance = np.var(bias_stack, axis=0)  # variance across frames per pixel
            self.read_noise = float(np.sqrt(np.mean(temporal_variance)))

            # 3. Compute dark current rate
            dark_stack = np.array(self.dark_frames, dtype=np.float32)
            dark_median = float(np.median(dark_stack))
            self.dark_current_rate = (dark_median - self.bias_offset) / exposure_sec

            # Ensure dark current is not negative
            if self.dark_current_rate < 0:
                self.dark_current_rate = 0.0

            # ========== RAW (16-bit) CALIBRATION ==========

            # 1. Compute bias offset from raw frames
            bias_stack_raw = np.array(self.bias_frames_raw, dtype=np.float32)
            self.bias_offset_raw = float(np.median(bias_stack_raw))

            # 2. Compute read noise using temporal variance (not spatial)
            temporal_variance_raw = np.var(bias_stack_raw, axis=0)
            self.read_noise_raw = float(np.sqrt(np.mean(temporal_variance_raw)))

            # 3. Compute dark current rate from raw frames
            dark_stack_raw = np.array(self.dark_frames_raw, dtype=np.float32)
            dark_median_raw = float(np.median(dark_stack_raw))
            self.dark_current_rate_raw = (
                dark_median_raw - self.bias_offset_raw
            ) / exposure_sec

            # Ensure dark current is not negative
            if self.dark_current_rate_raw < 0:
                self.dark_current_rate_raw = 0.0

            # 4. Calculate SQM for sky frames using the new calibration
            self._calculate_sky_sqm(exposure_sec)

            # 5. Save BOTH calibrations
            self._save_calibration()

            # Move to results
            self.state = CalibrationState.RESULTS

        except Exception as e:
            import traceback

            self.error_message = f"{type(e).__name__}: {str(e)}"
            traceback.print_exc()
            self.state = CalibrationState.ERROR

    def _calculate_sky_sqm(self, exposure_sec: float):
        """
        Calculate SQM for each sky frame using the newly measured calibration.
        Takes the median SQM across all frames.
        Uses 8-bit processed pipeline.
        """
        try:
            from PiFinder.sqm import SQM

            if len(self.sky_frames) == 0:
                logger.warning("No sky frames to calculate SQM")
                self.sqm_median = None
                return

            if len(self.sky_solutions) != len(self.sky_frames):
                logger.error(
                    f"Mismatch: {len(self.sky_frames)} frames but {len(self.sky_solutions)} solutions"
                )
                self.sqm_median = None
                return

            # Create SQM calculator with the newly measured calibration
            # Use PROCESSED (8-bit) pipeline
            camera_type_processed = f"{self.shared_state.camera_type()}_processed"
            sqm_calc = SQM(camera_type=camera_type_processed)

            # Manually set the calibration values we just measured
            if (
                sqm_calc.noise_estimator is not None
                and self.bias_offset is not None
                and self.read_noise is not None
                and self.dark_current_rate is not None
            ):
                sqm_calc.noise_estimator.profile.bias_offset = self.bias_offset
                sqm_calc.noise_estimator.profile.read_noise_adu = self.read_noise
                sqm_calc.noise_estimator.profile.dark_current_rate = (
                    self.dark_current_rate
                )

            self.sqm_values = []

            # Calculate SQM for each sky frame using its stored solution
            for i, (sky_frame, solution) in enumerate(
                zip(self.sky_frames, self.sky_solutions)
            ):
                if solution is None or solution.get("RA") is None:
                    # No valid solve - skip SQM calculation
                    logger.warning(f"No valid solve for sky frame {i}, skipping SQM")
                    continue

                altitude_deg = solution.get("Alt", 90.0)

                # Check if we have matched centroids (needed for SQM calculation)
                if "matched_centroids" not in solution:
                    logger.warning(
                        f"No matched centroids for sky frame {i}, skipping SQM"
                    )
                    continue

                centroids = solution["matched_centroids"]

                if len(centroids) == 0:
                    logger.warning(f"Empty centroids for sky frame {i}, skipping SQM")
                    continue

                # Calculate SQM for this frame (using processed 8-bit image)
                # Returns Tuple[Optional[float], Dict]
                sqm_value, _details = sqm_calc.calculate(
                    centroids=centroids,
                    solution=solution,
                    image=sky_frame,
                    exposure_sec=exposure_sec,
                    altitude_deg=altitude_deg,
                )

                if sqm_value is not None:
                    self.sqm_values.append(sqm_value)
                    logger.info(f"Sky frame {i}: SQM = {sqm_value:.2f}")

            # Calculate median SQM if we have any values
            if len(self.sqm_values) > 0:
                self.sqm_median = float(np.median(self.sqm_values))
                logger.info(
                    f"Median SQM from {len(self.sqm_values)} frames: {self.sqm_median:.2f}"
                )
            else:
                self.sqm_median = None
                logger.warning("No valid SQM values calculated from sky frames")

        except Exception as e:
            logger.error(f"Failed to calculate sky SQM: {e}")
            import traceback

            traceback.print_exc()
            self.sqm_median = None

    def _save_calibration(self):
        """Save calibration data for BOTH raw and processed profiles with measured values"""
        try:
            # Import here to avoid circular dependencies
            from PiFinder.sqm import NoiseFloorEstimator

            # Get camera type from shared state
            camera_type_raw_sensor = self.shared_state.camera_type()

            # ========== Save PROCESSED (8-bit) calibration ==========
            camera_type_processed = f"{camera_type_raw_sensor}_processed"
            estimator_processed = NoiseFloorEstimator(
                camera_type=camera_type_processed, enable_zero_sec_sampling=False
            )

            success_processed = estimator_processed.save_calibration(
                bias_offset=self.bias_offset,
                read_noise=self.read_noise,
                dark_current_rate=self.dark_current_rate,
            )

            if not success_processed:
                raise RuntimeError(
                    f"Failed to save processed calibration for {camera_type_processed}"
                )

            # ========== Save RAW (16-bit) calibration ==========
            camera_type_raw = camera_type_raw_sensor  # e.g., "imx296", "hq"
            estimator_raw = NoiseFloorEstimator(
                camera_type=camera_type_raw, enable_zero_sec_sampling=False
            )

            success_raw = estimator_raw.save_calibration(
                bias_offset=self.bias_offset_raw,
                read_noise=self.read_noise_raw,
                dark_current_rate=self.dark_current_rate_raw,
            )

            if not success_raw:
                raise RuntimeError(
                    f"Failed to save raw calibration for {camera_type_raw}"
                )

            # Tell solver to reload the calibration immediately (for processed profile)
            self._notify_solver_to_reload()

        except Exception as e:
            # Don't fail the whole wizard, just log the error
            import logging

            logger = logging.getLogger("PiFinder.SQMCalibration")
            logger.error(f"Failed to save calibration: {e}")

    def _notify_solver_to_reload(self):
        """Send command to solver to reload SQM calibration immediately"""
        try:
            # Use align_command queue to send reload command to solver
            if "align_command" in self.command_queues:
                self.command_queues["align_command"].put(["reload_sqm_calibration"])
            else:
                import logging

                logger = logging.getLogger("PiFinder.SQMCalibration")
                logger.warning(
                    "align_command queue not found, calibration will take effect on restart"
                )
        except Exception as e:
            import logging

            logger = logging.getLogger("PiFinder.SQMCalibration")
            logger.warning(f"Failed to notify solver: {e}")

    # ============================================
    # Key handlers
    # ============================================

    def key_square(self):
        """Square button advances through wizard states"""
        if self.state == CalibrationState.INTRO:
            # Start calibration
            self.state = CalibrationState.CAP_ON_INSTRUCTION

        elif self.state == CalibrationState.CAP_ON_INSTRUCTION:
            # User confirms lens cap is on, start bias capture
            self.state = CalibrationState.CAPTURING_BIAS
            self.current_frame = 0

        elif self.state == CalibrationState.CAP_OFF_INSTRUCTION:
            # User confirms lens cap is off, start sky capture
            self.state = CalibrationState.CAPTURING_SKY
            self.current_frame = 0

        elif self.state == CalibrationState.RESULTS:
            # Exit wizard
            if self.remove_from_stack:
                self.remove_from_stack()

        elif self.state == CalibrationState.ERROR:
            # Exit wizard
            if self.remove_from_stack:
                self.remove_from_stack()

    def key_number(self, number):
        """Number key cancels calibration or skips sky frames"""
        if number == 0:
            # If capturing sky frames, skip to analysis
            if self.state == CalibrationState.CAPTURING_SKY:
                logger.info("User skipped sky frame capture")
                self.state = CalibrationState.ANALYZING
                self.current_frame = 0
            # Otherwise cancel and exit
            elif self.state in [
                CalibrationState.INTRO,
                CalibrationState.CAP_ON_INSTRUCTION,
                CalibrationState.CAP_OFF_INSTRUCTION,
            ]:
                if self.remove_from_stack:
                    self.remove_from_stack()

    # ============================================
    # Marking menu for debug options
    # ============================================

    def _create_marking_menu(self):
        """Create marking menu for calibration options"""
        debug_label = "Dbg ON" if self.save_frames_enabled else "Dbg"
        return MarkingMenu(
            left=MarkingMenuOption(
                label=debug_label,
                callback=self._toggle_save_frames,
            ),
            down=MarkingMenuOption(),
            right=MarkingMenuOption(),
        )

    def _toggle_save_frames(self, marking_menu, selected_item):
        """Toggle saving calibration frames to disk"""
        self.save_frames_enabled = not self.save_frames_enabled

        # Update marking menu to reflect new state
        self.marking_menu = self._create_marking_menu()

        if self.save_frames_enabled:
            # Create timestamped directory for this calibration run
            import datetime
            from PiFinder import utils

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.calibration_output_dir = os.path.join(
                utils.data_dir, "calibration", f"sqm_cal_{timestamp}"
            )
            os.makedirs(self.calibration_output_dir, exist_ok=True)

            if hasattr(self, "console_queue") and self.console_queue:
                self.console_queue.put(
                    f"CAL: Saving to {os.path.basename(self.calibration_output_dir)}"
                )
        else:
            if hasattr(self, "console_queue") and self.console_queue:
                self.console_queue.put("CAL: Frame saving disabled")

        return True  # Exit marking menu
