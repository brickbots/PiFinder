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
import numpy as np
from enum import Enum
from typing import Optional, List

from PiFinder.ui.base import UIModule


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

        # Separate storage for each frame type
        self.bias_frames: List[np.ndarray] = []
        self.dark_frames: List[np.ndarray] = []
        self.sky_frames: List[np.ndarray] = []

        # Calibration results
        self.bias_offset: Optional[float] = None
        self.read_noise: Optional[float] = None
        self.dark_current_rate: Optional[float] = None
        self.sky_brightness: Optional[float] = None

        # Store original camera settings to restore later
        self.original_exposure = None
        self.original_gain = None

        # Get current exposure time for dark/sky frames
        metadata = self.shared_state.last_image_metadata()
        self.exposure_time_us = metadata.get("exposure_time", 500000)  # microseconds

    def active(self):
        """Called when module becomes active"""
        # Store original camera settings
        metadata = self.shared_state.last_image_metadata()
        self.original_exposure = metadata.get("exposure_time", 500000)

        # Start with intro screen
        self.state = CalibrationState.INTRO
        self.update(force=True)

    def inactive(self):
        """Called when module becomes inactive"""
        # Restore original camera settings if needed
        if self.original_exposure is not None:
            self.command_queues["camera"].put(f"set_exp:{self.original_exposure}")

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
            "SQM CALIBRATION",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        lines = [
            "This wizard will",
            "calibrate the SQM",
            "noise floor.",
            "",
            "You will need:",
            "• Lens cap",
            "• Dark location",
            "• 2-3 minutes",
        ]

        y = 38
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
            fill=self.colors.get(64),
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
            fill=self.colors.get(64),
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
            fill=self.colors.get(64),
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
        """Draw final results"""
        self.draw.text(
            (10, 18),
            "CALIBRATION DONE",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        y = 36
        if self.bias_offset is not None:
            self.draw.text(
                (10, y),
                f"Bias: {self.bias_offset:.1f} ADU",
                font=self.fonts.base.font,
                fill=self.colors.get(192),
            )
            y += self.fonts.base.height + 2

        if self.read_noise is not None:
            self.draw.text(
                (10, y),
                f"Read: {self.read_noise:.2f} ADU",
                font=self.fonts.base.font,
                fill=self.colors.get(192),
            )
            y += self.fonts.base.height + 2

        if self.dark_current_rate is not None:
            self.draw.text(
                (10, y),
                f"Dark: {self.dark_current_rate:.3f} e/s",
                font=self.fonts.base.font,
                fill=self.colors.get(192),
            )
            y += self.fonts.base.height + 2

        if self.sky_brightness is not None:
            self.draw.text(
                (10, y),
                f"SQM: {self.sky_brightness:.2f}",
                font=self.fonts.base.font,
                fill=self.colors.get(192),
            )
            y += self.fonts.base.height + 2

        # Legend
        self.draw.text(
            (10, 110),
            f"{self._SQUARE_} DONE",
            font=self.fonts.base.font,
            fill=self.colors.get(64),
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
            fill=self.colors.get(64),
        )

    # ============================================
    # Frame capture methods
    # ============================================

    def _capture_bias_frame(self):
        """Capture a bias frame (0s exposure)"""
        if self.current_frame == 0:
            # First frame: set exposure to minimum (closest to 0)
            self.command_queues["camera"].put("set_exp:1")  # Minimum exposure
            time.sleep(0.2)  # Wait for camera to apply setting
            self.bias_frames = []

        # Capture current image
        img = self.camera_image.copy()
        img = img.convert(mode="L")
        np_image = np.asarray(img, dtype=np.uint8)
        self.bias_frames.append(np_image)

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
        """Capture a dark frame (actual exposure with cap on)"""
        if self.current_frame == 0:
            self.dark_frames = []

        # Capture current image
        img = self.camera_image.copy()
        img = img.convert(mode="L")
        np_image = np.asarray(img, dtype=np.uint8)
        self.dark_frames.append(np_image)

        self.current_frame += 1

        if self.current_frame >= self.num_frames:
            # Done capturing dark frames
            self.state = CalibrationState.CAP_OFF_INSTRUCTION
            self.current_frame = 0
        else:
            time.sleep(0.5)  # Wait for full exposure between frames

    def _capture_sky_frame(self):
        """Capture a sky frame (actual exposure, needs plate solve)"""
        if self.current_frame == 0:
            self.sky_frames = []

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

        # Valid solve, capture frame
        img = self.camera_image.copy()
        img = img.convert(mode="L")
        np_image = np.asarray(img, dtype=np.uint8)
        self.sky_frames.append(np_image)

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
        """Analyze captured frames and compute calibration parameters"""
        try:
            # This runs once, then moves to results
            if self.bias_offset is not None:
                # Already analyzed, show results
                self.state = CalibrationState.RESULTS
                return

            # Check that we have enough frames
            if len(self.bias_frames) < self.num_frames:
                self.error_message = f"Not enough bias frames ({len(self.bias_frames)})"
                self.state = CalibrationState.ERROR
                return

            if len(self.dark_frames) < self.num_frames:
                self.error_message = f"Not enough dark frames ({len(self.dark_frames)})"
                self.state = CalibrationState.ERROR
                return

            # 1. Compute bias offset (median of all pixels in all bias frames)
            bias_stack = np.array(self.bias_frames, dtype=np.float32)
            self.bias_offset = float(np.median(bias_stack))

            # 2. Compute read noise (std of all pixels in all bias frames)
            self.read_noise = float(np.std(bias_stack))

            # 3. Compute dark current rate
            # dark_current = (dark_median - bias_offset) / exposure_time
            dark_stack = np.array(self.dark_frames, dtype=np.float32)
            dark_median = float(np.median(dark_stack))
            exposure_sec = self.exposure_time_us / 1_000_000.0

            # Dark current in ADU/sec
            self.dark_current_rate = (dark_median - self.bias_offset) / exposure_sec

            # Ensure dark current is not negative (would indicate measurement error)
            if self.dark_current_rate < 0:
                self.dark_current_rate = 0.0

            # 4. Compute sky brightness from sky frames (optional)
            if len(self.sky_frames) >= self.num_frames:
                # This would require running the full SQM calculation
                # For now, we'll skip this or set a placeholder
                self.sky_brightness = None
            else:
                self.sky_brightness = None

            # 5. Save calibration using NoiseFloorEstimator
            self._save_calibration()

            # Move to results
            self.state = CalibrationState.RESULTS

        except Exception as e:
            import traceback

            self.error_message = f"{type(e).__name__}: {str(e)}"
            traceback.print_exc()
            self.state = CalibrationState.ERROR

    def _save_calibration(self):
        """Save calibration data using NoiseFloorEstimator"""
        try:
            # Import here to avoid circular dependencies
            from PiFinder.noise_floor_estimator import NoiseFloorEstimator

            # Get camera type from shared state and use "_processed" profile
            # since images are 8-bit processed
            camera_type_raw = self.shared_state.camera_type()
            camera_type = f"{camera_type_raw}_processed"

            estimator = NoiseFloorEstimator(
                camera_type=camera_type, enable_zero_sec_sampling=False
            )

            # Save calibration
            success = estimator.save_calibration(
                bias_offset=self.bias_offset,
                read_noise=self.read_noise,
                dark_current_rate=self.dark_current_rate,
            )

            if not success:
                raise RuntimeError("Failed to save calibration")

            # Tell solver to reload the calibration immediately
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
        """Number key cancels calibration"""
        if number == 0:
            # Cancel and exit
            if self.remove_from_stack:
                self.remove_from_stack()
