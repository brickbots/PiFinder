#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
SQM Calibration Wizard

This optional wizard refines the factory SQM (Sky Quality Meter) sensor-noise
defaults. Normal SQM operation requires no user calibration. The process:

1. Captures minimum-exposure bias frames with the lens cap on to measure bias
   and temporal read noise
2. Captures a multi-exposure dark sequence to fit mean dark current
3. Captures sky frames (actual exposure without cap) to measure actual sky brightness
4. Calculates noise parameters and updates the camera profile
5. Saves calibration data for future use

The wizard guides the user through lens cap placement and displays progress.
"""

import copy
import json
import time
import os
import logging
import numpy as np
from enum import Enum
from typing import Optional, List

from PiFinder.solver import (
    _derotate_centroids,
    _extract_raw_photometry_image,
    _scale_solution_centroids,
)
from PiFinder.types.positioning import PointingEstimate, ReloadSqmCalibration
from PiFinder.ui.base import UIModule
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder import timez, utils

logger = logging.getLogger("PiFinder.SQMCalibration")


class CalibrationState(Enum):
    """Calibration wizard states"""

    INTRO = "intro"  # Introduction screen
    CAP_ON_INSTRUCTION = "cap_on"  # Instruction to put lens cap on
    CAPTURING_BIAS = "bias"  # Capturing minimum-exposure bias frames
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

    def __init__(self, *args, **kwargs) -> None:
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

        # Frame storage - RAW (16-bit); SQM photometry is raw-only
        self.bias_frames_raw: List[np.ndarray] = []
        self.dark_frames_raw: List[np.ndarray] = []
        self.dark_frame_exposures_sec: List[float] = []
        # Per-frame capture records persisted in the calibration report JSON:
        # the fitted scalars alone cannot reveal ramp curvature (short-exposure
        # pedestal elevation) or wrong-exposure frames after the fact.
        self.report_bias_frames: List[dict] = []
        self.report_dark_frames: List[dict] = []
        self.sky_frames_raw: List[np.ndarray] = []

        # Store solution for each sky frame (needed for SQM calculation)
        self.sky_solutions: List[PointingEstimate] = []

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
        self.original_exposure_setting = None
        self.original_gain = None
        self.original_ae_state = None

        # Exposure time will be set in active() based on current exposure
        # with minimum of 400ms to ensure good SNR
        self.exposure_time_us: int = 400000

        # Timeout tracking for sky frame capture
        self.sky_capture_start_time = None
        self.sky_capture_timeout = 30  # seconds - skip if no solve after this

    def active(self):
        """Called when module becomes active"""
        # A module instance can be reopened. Never reuse frames, results, or a
        # timeout from an earlier calibration run.
        self.current_frame = 0
        self.bias_frames_raw = []
        self.dark_frames_raw = []
        self.dark_frame_exposures_sec = []
        self.report_bias_frames = []
        self.report_dark_frames = []
        self.sky_frames_raw = []
        self.sky_solutions = []
        self.bias_offset_raw = None
        self.read_noise_raw = None
        self.dark_current_rate_raw = None
        self.sky_brightness_raw = None
        self.sqm_median = None
        self.sqm_values = []
        self.sky_capture_start_time = None

        # Store original camera settings
        metadata = self.shared_state.last_image_metadata() or {}
        self.original_exposure = metadata.get("exposure_time", 500000)
        self.original_exposure_setting = self.config_object.get_option("camera_exp")

        # Use max(current_exposure, 400ms) to ensure good SNR
        # but preserve higher exposure if already set
        self.exposure_time_us = max(self.original_exposure, 400000)

        # Set exposure for calibration
        self._set_calibration_exposure(self.exposure_time_us)
        time.sleep(0.2)  # Wait for camera to apply setting

        # Start with intro screen
        self.state = CalibrationState.INTRO
        self.update(force=True)

    def inactive(self):
        """Called when module becomes inactive"""
        # Restore the exposure mode, not merely the most recent numeric value.
        if self.original_exposure_setting == "auto":
            self.command_queues["camera"].put("set_exp:auto")
        elif self.original_exposure_setting is not None:
            self.command_queues["camera"].put(
                f"set_exp_transient:{self.original_exposure_setting}"
            )
        elif self.original_exposure is not None:
            self.command_queues["camera"].put(
                f"set_exp_transient:{self.original_exposure}"
            )
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
        tb = self.display_class.titlebar_height
        self.draw.text(
            (10, tb + 3),
            "SQM CAL",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        lines = [
            "Optional refinement",
            "",
            "Need:",
            "• Lens cap",
            "• ~3 minutes",
        ]

        y = tb + 23
        for line in lines:
            self.draw.text(
                (10, y), line, font=self.fonts.base.font, fill=self.colors.get(192)
            )
            y += self.fonts.base.height + 2

        # Legend
        self.draw.text(
            (10, self.display_class.resY - self.fonts.base.height - 7),
            f"{self._SQUARE_} START  0 CANCEL",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    def _draw_cap_on_instruction(self):
        """Draw lens cap on instruction"""
        tb = self.display_class.titlebar_height
        self.draw.text(
            (10, tb + 13),
            "PUT LENS CAP ON",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        y = tb + 33
        for line in ("Cover the camera", "lens completely to", "block all light."):
            self.draw.text(
                (10, y), line, font=self.fonts.base.font, fill=self.colors.get(192)
            )
            y += self.fonts.base.height + 1

        # Legend
        self.draw.text(
            (10, self.display_class.resY - self.fonts.base.height - 7),
            f"{self._SQUARE_} READY  0 CANCEL",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    def _draw_cap_off_instruction(self):
        """Draw lens cap off instruction"""
        tb = self.display_class.titlebar_height
        self.draw.text(
            (10, tb + 13),
            "REMOVE LENS CAP",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        y = tb + 33
        for line in ("Remove the cap and", "point at dark sky.", "Wait for solve."):
            self.draw.text(
                (10, y), line, font=self.fonts.base.font, fill=self.colors.get(192)
            )
            y += self.fonts.base.height + 1

        # Legend - show skip option for indoor calibration, anchored to bottom
        base_h = self.fonts.base.height
        skip_y = self.display_class.resY - base_h - 7
        self.draw.text(
            (10, skip_y - (base_h + 2)),
            f"{self._SQUARE_} READY",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )
        self.draw.text(
            (10, skip_y),
            "0 SKIP (indoor cal)",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    def _draw_progress(self, label: str, current: int, total: int):
        """Draw progress bar for frame capture"""
        tb = self.display_class.titlebar_height
        self.draw.text(
            (10, tb + 3),
            f"{label} FRAMES",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        # Progress text
        self.draw.text(
            (10, tb + 23),
            f"{current} / {total}",
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )

        # Progress bar spans the width with a symmetric margin
        bar_x = round(self.display_class.resX * 10 / 128)
        bar_y = tb + 53
        bar_width = self.display_class.resX - 2 * bar_x
        bar_height = round(self.display_class.resY * 12 / 128)
        # message row sits just below the bar
        msg_y = bar_y + bar_height + 8

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
                        (10, msg_y),
                        f"Wait for solve: {remaining}s",
                        font=self.fonts.base.font,
                        fill=self.colors.get(128),
                    )
                else:
                    self.draw.text(
                        (10, msg_y),
                        "No solve detected",
                        font=self.fonts.base.font,
                        fill=self.colors.get(128),
                    )
            else:
                self.draw.text(
                    (10, msg_y),
                    "Hold steady...",
                    font=self.fonts.base.font,
                    fill=self.colors.get(64),
                )
            # Show skip option
            self.draw.text(
                (10, self.display_class.resY - self.fonts.base.height - 7),
                "0: SKIP SKY",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
        else:
            self.draw.text(
                (10, msg_y),
                "Keep cap on...",
                font=self.fonts.base.font,
                fill=self.colors.get(64),
            )

    def _draw_analyzing(self):
        """Draw analyzing screen"""
        tb = self.display_class.titlebar_height
        self.draw.text(
            (10, tb + 23),
            "ANALYZING...",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        y = tb + 43
        for line in ("Computing noise", "parameters..."):
            self.draw.text(
                (10, y), line, font=self.fonts.base.font, fill=self.colors.get(128)
            )
            y += self.fonts.base.height + 1

    def _draw_results(self):
        """Draw final results (raw calibration)"""
        tb = self.display_class.titlebar_height
        self.draw.text(
            (10, tb + 1),
            "CAL COMPLETE",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        y = tb + 19

        # Bias offset
        if self.bias_offset_raw is not None:
            self.draw.text(
                (10, y),
                f"Bias: {self.bias_offset_raw:6.1f}",
                font=self.fonts.base.font,
                fill=self.colors.get(192),
            )
            y += self.fonts.base.height + 2

        # Read noise
        if self.read_noise_raw is not None:
            self.draw.text(
                (10, y),
                f"Read: {self.read_noise_raw:6.2f}",
                font=self.fonts.base.font,
                fill=self.colors.get(192),
            )
            y += self.fonts.base.height + 2

        # Dark current
        if self.dark_current_rate_raw is not None:
            self.draw.text(
                (10, y),
                f"Dark: {self.dark_current_rate_raw:6.2f}",
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
            (10, self.display_class.resY - self.fonts.base.height - 7),
            f"{self._SQUARE_} DONE",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    def _draw_error(self):
        """Draw error screen"""
        tb = self.display_class.titlebar_height
        self.draw.text(
            (10, tb + 13),
            "ERROR",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        # Wrap error message
        y = tb + 33
        words = self.error_message.split()
        line = ""
        for word in words:
            test_line = line + " " + word if line else word
            if len(test_line) <= self.fonts.base.line_length:
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
            (10, self.display_class.resY - self.fonts.base.height - 7),
            f"{self._SQUARE_} EXIT",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    # ============================================
    # Frame capture methods
    # ============================================

    def _set_calibration_exposure(self, exposure_us: int) -> None:
        """Set a temporary exposure without changing the saved user setting."""
        self.command_queues["camera"].put(f"set_exp_transient:{exposure_us}")

    def _capture_and_wait(self, exposure_us: int) -> float:
        """Request one frame and return its identifying exposure-end time."""
        previous_metadata = self.shared_state.last_image_metadata() or {}
        previous_end = float(previous_metadata.get("exposure_end", 0.0))
        self.command_queues["camera"].put("capture")

        timeout = max(5.0, 3 * exposure_us / 1_000_000.0 + 1.0)
        deadline = time.time() + timeout
        while time.time() < deadline:
            metadata = self.shared_state.last_image_metadata() or {}
            exposure_end = float(metadata.get("exposure_end", 0.0))
            metadata_exposure = int(metadata.get("exposure_time", 0))
            if (
                exposure_end > previous_end
                and abs(metadata_exposure - exposure_us) <= 1000
            ):
                return exposure_end
            time.sleep(0.05)
        raise TimeoutError(f"Timed out waiting for {exposure_us}µs calibration frame")

    def _wait_for_solution_at(self, exposure_end: float) -> PointingEstimate:
        """Return the successful plate solution for an identified frame."""
        deadline = time.time() + self.sky_capture_timeout
        while time.time() < deadline:
            solution = self.shared_state.solution()
            if (
                solution is not None
                and solution.has_pointing()
                and solution.last_solve_attempt == exposure_end
                and solution.last_solve_success == exposure_end
                and solution.matched_centroids is not None
                and solution.matched_stars is not None
            ):
                return copy.deepcopy(solution)
            time.sleep(0.05)
        raise TimeoutError("Timed out waiting for matching sky-frame solution")

    def _capture_bias_frame(self):
        """Capture a minimum-exposure raw bias frame."""
        if self.current_frame == 0:
            # First frame: set exposure to minimum (closest to 0)
            self._set_calibration_exposure(1)  # Minimum exposure
            time.sleep(0.2)  # Wait for camera to apply setting
            self.bias_frames_raw = []

        # Set save flag if debug enabled, then capture
        if self.save_frames_enabled:
            filename = os.path.join(
                self.calibration_output_dir, f"bias_{self.current_frame:03d}.png"
            )
            self.command_queues["camera"].put(f"save:{filename}")
        try:
            self._capture_and_wait(1)
        except TimeoutError as exc:
            logger.warning("%s", exc)
            return

        # Get RAW image (16-bit) from shared state
        raw_array = self.shared_state.cam_raw()
        if raw_array is not None:
            self.bias_frames_raw.append(raw_array.copy())
            self.report_bias_frames.append(self._frame_report(raw_array, 1))

        self.current_frame += 1

        if self.current_frame >= self.num_frames:
            # Done capturing bias frames
            self.state = CalibrationState.CAPTURING_DARK
            self.current_frame = 0
            # Restore original exposure for dark frames
            self._set_calibration_exposure(self.exposure_time_us)
            time.sleep(0.2)
        else:
            time.sleep(0.1)  # Small delay between frames

    def _capture_dark_frame(self):
        """Capture one point in a multi-exposure raw dark sequence."""
        if self.current_frame == 0:
            self.dark_frames_raw = []
            self.dark_frame_exposures_sec = []

        # A single nonzero exposure cannot separate slope from an offset
        # error. Span down to (near) the sensor minimum: the short-exposure
        # region is where clamp-driven pedestal elevation lives (measured on
        # the imx462: +2.9 ADU at 25 ms decaying to 0 at ~300 ms), and a
        # one-decade ramp cannot see it. The driver clamps too-short requests;
        # the report records the ACTUAL delivered exposure either way.
        minimum_exposure_us = max(100, int(self.exposure_time_us / 5000))
        exposure_schedule_us = np.geomspace(
            minimum_exposure_us,
            self.exposure_time_us,
            self.num_frames,
        ).astype(int)
        exposure_us = int(exposure_schedule_us[self.current_frame])
        self._set_calibration_exposure(exposure_us)
        time.sleep(0.2)

        # Set save flag if debug enabled, then capture
        if self.save_frames_enabled:
            filename = os.path.join(
                self.calibration_output_dir, f"dark_{self.current_frame:03d}.png"
            )
            self.command_queues["camera"].put(f"save:{filename}")
        try:
            self._capture_and_wait(exposure_us)
        except TimeoutError as exc:
            logger.warning("%s", exc)
            return

        # Get RAW image (16-bit) from shared state
        raw_array = self.shared_state.cam_raw()
        if raw_array is not None:
            self.dark_frames_raw.append(raw_array.copy())
            report = self._frame_report(raw_array, exposure_us)
            self.report_dark_frames.append(report)
            # Fit against the exposure the driver says it delivered, not the
            # request: the imx477 intermittently delivers frames at half the
            # requested exposure (insufficient settle after an exposure
            # change), which silently corrupts a requested-exposure fit.
            actual_us = report.get("actual_exposure_us")
            self.dark_frame_exposures_sec.append(
                (actual_us if actual_us else exposure_us) / 1_000_000.0
            )

        self.current_frame += 1

        if self.current_frame >= self.num_frames:
            # Done capturing dark frames
            self.state = CalibrationState.CAP_OFF_INSTRUCTION
            self.current_frame = 0
            self._set_calibration_exposure(self.exposure_time_us)
            time.sleep(0.2)
        else:
            time.sleep(0.5)  # Wait for full exposure between frames

    def _capture_sky_frame(self):
        """Capture a sky frame (actual exposure, needs plate solve) - both processed and raw"""
        if self.current_frame == 0:
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

        # Capture first, then accept only the solve carrying this exact frame's
        # exposure timestamp. A previous solve has the wrong centroids as soon
        # as the telescope moves.
        if self.save_frames_enabled:
            filename = os.path.join(
                self.calibration_output_dir, f"sky_{self.current_frame:03d}.png"
            )
            self.command_queues["camera"].put(f"save:{filename}")
        try:
            exposure_end = self._capture_and_wait(self.exposure_time_us)
        except TimeoutError as exc:
            logger.warning("%s", exc)
            return

        # Get RAW image (16-bit) from shared state; solution is stored
        # alongside so the two lists stay index-aligned.
        raw_array = self.shared_state.cam_raw()
        try:
            solution = self._wait_for_solution_at(exposure_end)
        except TimeoutError as exc:
            logger.warning("%s", exc)
            if self.current_frame == 0:
                self.state = CalibrationState.ANALYZING
            return

        if raw_array is not None:
            self.sky_frames_raw.append(raw_array.copy())
            self.sky_solutions.append(solution)

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
        """Analyze captured raw frames and compute calibration parameters"""
        try:
            # This runs once, then moves to results
            if self.bias_offset_raw is not None:
                # Already analyzed, show results
                self.state = CalibrationState.RESULTS
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

            # ========== RAW (16-bit) CALIBRATION ==========

            # 1. Compute bias offset from raw frames
            bias_stack_raw = np.array(self.bias_frames_raw, dtype=np.float32)
            self.bias_offset_raw = float(np.median(bias_stack_raw))

            # 2. Compute read noise using temporal variance (not spatial)
            temporal_variance_raw = np.var(bias_stack_raw, axis=0, ddof=1)
            self.read_noise_raw = float(np.sqrt(np.mean(temporal_variance_raw)))

            # 3. Fit mean dark signal across the exposure sequence.
            self.dark_current_rate_raw = self._fit_dark_current_rate(
                self.dark_frames_raw,
                self.dark_frame_exposures_sec,
                self.bias_offset_raw,
            )

            # 4. Calculate SQM for sky frames using the new calibration
            self._calculate_sky_sqm(exposure_sec)

            # 5. Save the raw-sensor calibration and the per-frame report.
            self._save_calibration()
            self._save_calibration_report()

            # Move to results
            self.state = CalibrationState.RESULTS

        except Exception as e:
            import traceback

            self.error_message = f"{type(e).__name__}: {str(e)}"
            traceback.print_exc()
            self.state = CalibrationState.ERROR

    @staticmethod
    def _fit_dark_current_rate(
        frames: List[np.ndarray],
        exposures_sec: List[float],
        bias_offset: float,
    ) -> float:
        """Fit ``median_dark - bias = rate * exposure`` through the origin."""
        if len(frames) != len(exposures_sec) or len(frames) < 2:
            raise ValueError("Dark-current fit requires matching multi-exposure frames")

        times = np.asarray(exposures_sec, dtype=np.float64)
        signals = np.asarray(
            [float(np.median(frame)) - bias_offset for frame in frames],
            dtype=np.float64,
        )
        valid = np.isfinite(times) & np.isfinite(signals) & (times > 0)
        if np.count_nonzero(valid) < 2:
            raise ValueError("Dark-current fit has too few valid exposure points")

        denominator = float(np.dot(times[valid], times[valid]))
        if denominator <= 0:
            raise ValueError("Dark-current fit has zero exposure leverage")
        rate = float(np.dot(times[valid], signals[valid]) / denominator)
        return max(0.0, rate)

    def _calculate_sky_sqm(self, exposure_sec: float):
        """
        Calculate SQM for each sky frame using the newly measured calibration.
        Takes the median SQM across all frames.
        Uses the same raw-photometry, Gaia-band, annulus, and rolling-wing
        pipeline as normal operation. This is an optional calibration sanity
        check; normal SQM does not require the wizard.
        """
        try:
            from PiFinder.sqm import SQM
            from PiFinder.sqm.wings import WingEstimator

            if len(self.sky_frames_raw) == 0:
                logger.warning("No sky frames to calculate SQM")
                self.sqm_median = None
                return

            if len(self.sky_solutions) != len(self.sky_frames_raw):
                logger.error(
                    f"Mismatch: {len(self.sky_frames_raw)} frames but "
                    f"{len(self.sky_solutions)} solutions"
                )
                self.sqm_median = None
                return

            # Create SQM calculator with the newly measured raw calibration
            sqm_calc = SQM(camera_type=self.shared_state.camera_type())

            # Manually set the calibration values we just measured
            if self.bias_offset_raw is not None:
                sqm_calc.profile.bias_offset = self.bias_offset_raw
            if self.read_noise_raw is not None:
                sqm_calc.profile.read_noise_adu = self.read_noise_raw
            if self.dark_current_rate_raw is not None:
                sqm_calc.profile.dark_current_rate = self.dark_current_rate_raw
                # This value came from the multi-exposure fit above, so the
                # calibration preview must apply it even before the JSON is
                # written and reloaded by the solver.
                sqm_calc.noise_floor_estimator.dark_current_calibrated = True
                sqm_calc.noise_floor_estimator.calibration_loaded = True

            self.sqm_values = []
            saturation_threshold = int(0.70 * (2**sqm_calc.profile.bit_depth - 1))
            wing_estimator = WingEstimator()

            # Calculate SQM for each raw sky frame using its stored solution
            for i, (sky_frame, solution) in enumerate(
                zip(self.sky_frames_raw, self.sky_solutions)
            ):
                if solution is None or not solution.has_pointing():
                    # No valid solve - skip SQM calculation
                    logger.warning(f"No valid solve for sky frame {i}, skipping SQM")
                    continue

                altitude_deg = solution.Alt

                # Check if we have matched centroids (needed for SQM calculation)
                if solution.matched_centroids is None or solution.matched_stars is None:
                    logger.warning(
                        f"No matched centroids/stars for sky frame {i}, skipping SQM"
                    )
                    continue

                centroids = solution.matched_centroids

                if len(centroids) == 0:
                    logger.warning(f"Empty centroids for sky frame {i}, skipping SQM")
                    continue

                # Raw photometry image (green channel for Bayer sensors);
                # centroids come from the 512px solve image and are rescaled.
                green = _extract_raw_photometry_image(sky_frame, sqm_calc.profile)
                if green is None:
                    logger.warning(f"Bad raw frame {i}, skipping SQM")
                    continue

                # Adapter dict for SQM (sqm.calculate still consumes a
                # raw-tetra3-shaped dict so SQM stays loose of our types).
                scale = green.shape[0] / 512.0
                raw_solution = {
                    "FOV": solution.diagnostics.FOV,
                    "matched_centroids": solution.matched_centroids,
                    "matched_stars": solution.matched_stars,
                }
                if solution.matched_catID is not None:
                    raw_solution["matched_catID"] = solution.matched_catID
                sqm_solution = _scale_solution_centroids(raw_solution, scale)
                calc_centroids = np.asarray(centroids, dtype=np.float64) * scale

                # Solve/display images are rotated relative to the stored raw
                # frame. Apply the same counter-rotation as production SQM.
                try:
                    solve_rotation = self.shared_state.solve_image_rotation()
                except (BrokenPipeError, ConnectionResetError, AttributeError):
                    solve_rotation = None
                if solve_rotation:
                    side = green.shape[0]
                    sqm_solution["matched_centroids"] = _derotate_centroids(
                        sqm_solution["matched_centroids"], solve_rotation, side
                    )
                    calc_centroids = _derotate_centroids(
                        calc_centroids, solve_rotation, side
                    )

                wing_correction = wing_estimator.correction()

                # Returns Tuple[Optional[float], Dict]
                sqm_value, _details = sqm_calc.calculate(
                    centroids=calc_centroids,
                    solution=sqm_solution,
                    image=green,
                    exposure_sec=exposure_sec,
                    altitude_deg=altitude_deg,
                    saturation_threshold=saturation_threshold,
                    image_pixels_per_side=green.shape[0],
                    mzero_correction=wing_correction,
                )

                wing_estimator.add_frame(
                    green,
                    sqm_solution["matched_centroids"],
                    saturation_threshold,
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

    def _frame_report(self, raw_array, requested_exposure_us: int) -> dict:
        """Per-frame record for the calibration report JSON (units in names)."""
        metadata = self.shared_state.last_image_metadata() or {}
        arr = np.asarray(raw_array)
        return {
            "requested_exposure_us": int(requested_exposure_us),
            "actual_exposure_us": metadata.get("actual_exposure_us"),
            "sensor_temp_c": metadata.get("sensor_temp_c"),
            "median_adu": float(np.median(arr)),
            "mad_adu": float(np.median(np.abs(arr - np.median(arr)))),
            "p01_adu": float(np.percentile(arr, 1)),
            "p99_adu": float(np.percentile(arr, 99)),
        }

    def _save_calibration_report(self):
        """Persist the per-frame evidence beside the fitted scalars.

        The calibration JSON keeps only three fitted numbers; this report
        keeps the ramp itself, so short-exposure curvature, wrong-exposure
        frames, and temperature context stay analyzable after the fact.
        Best-effort: a report failure must never fail the wizard.
        """
        try:
            camera_type = self.shared_state.camera_type()
            stamp = timez.local_now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(
                str(utils.data_dir),
                f"sqm_calibration_report_{camera_type}_{stamp}.json",
            )
            payload = {
                "camera_type": camera_type,
                "timestamp": timez.local_now().isoformat(),
                "fitted": {
                    "bias_offset_adu": self.bias_offset_raw,
                    "read_noise_adu": self.read_noise_raw,
                    "dark_current_rate_adu_per_sec": self.dark_current_rate_raw,
                },
                "bias_frames": self.report_bias_frames,
                "dark_frames": self.report_dark_frames,
                "dark_fit_exposures_sec": list(self.dark_frame_exposures_sec),
                "num_frames_per_stage": self.num_frames,
            }
            with open(path, "w") as handle:
                json.dump(payload, handle, indent=2, default=str)
            logger.info("Saved calibration report to %s", path)
        except Exception as exc:
            logger.warning("Could not save calibration report: %s", exc)

    def _save_calibration(self):
        """Save the measured raw calibration for the camera profile"""
        try:
            # Import here to avoid circular dependencies
            from PiFinder.sqm import NoiseFloorEstimator

            camera_type_raw = self.shared_state.camera_type()  # e.g., "imx296", "hq"
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
                self.command_queues["align_command"].put(ReloadSqmCalibration())
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
            # Skip sky frames and proceed to analysis (indoor calibration)
            if self.state == CalibrationState.CAP_OFF_INSTRUCTION:
                logger.info("User skipped sky frames (indoor calibration)")
                self.state = CalibrationState.ANALYZING
                self.current_frame = 0
            # If capturing sky frames, skip to analysis
            elif self.state == CalibrationState.CAPTURING_SKY:
                logger.info("User skipped remaining sky frame capture")
                self.state = CalibrationState.ANALYZING
                self.current_frame = 0
            # Otherwise cancel and exit
            elif self.state in [
                CalibrationState.INTRO,
                CalibrationState.CAP_ON_INSTRUCTION,
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
            from PiFinder import utils

            timestamp = timez.local_now().strftime("%Y%m%d_%H%M%S")
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
