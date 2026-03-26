#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
SQM Sweep UI

Multi-step wizard for capturing exposure sweeps with reference SQM
and full metadata for calibration validation.
"""

import json
import logging
import time
from enum import Enum
from pathlib import Path

import numpy as np

from PiFinder import utils
from PiFinder.ui.base import UIModule

logger = logging.getLogger("PiFinder.SQMSweep")


class SweepState(Enum):
    """Sweep wizard states"""

    ASK_SQM = "ask_sqm"  # Ask for reference SQM value
    CONFIRM = "confirm"  # Confirm ready to start
    CAPTURING = "capturing"  # Capturing sweep
    COMPLETE = "complete"  # Sweep done


class UISQMSweep(UIModule):
    """
    SQM Sweep Wizard

    Steps:
    1. Ask user for reference SQM value from external meter
    2. Confirm ready to start
    3. Capture exposure sweep images
    4. Save full metadata (SQM details, solve, noise floor estimator)
    """

    __title__ = "SQM SWEEP"
    __help_name__ = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = SweepState.ASK_SQM
        self.reference_sqm = None
        self.sqm_input = ""  # User input for SQM value
        self.sweep_started = False
        self.start_time = None
        self.sweep_dir = None  # Track the actual sweep directory
        self.initial_file_count = None  # Files that existed before we started
        self.total_images = 20  # Expected number of images
        self.estimated_duration = 60  # ~1 minute estimated

    def active(self):
        """Called when module becomes active"""
        self.state = SweepState.ASK_SQM
        self.update(force=True)

    def update(self, force=False):
        """Update display based on current state"""
        self.clear_screen()

        if self.state == SweepState.ASK_SQM:
            self._draw_ask_sqm()
        elif self.state == SweepState.CONFIRM:
            self._draw_confirm()
        elif self.state == SweepState.CAPTURING:
            self._draw_capturing()
        elif self.state == SweepState.COMPLETE:
            self._draw_complete()

        return self.screen_update(title_bar=True)

    def _draw_ask_sqm(self):
        """Draw SQM input screen"""
        self.draw.text(
            (10, 15),
            "REFERENCE SQM",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        self.draw.text(
            (10, 35),
            "Enter SQM from",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )
        self.draw.text(
            (10, 47),
            "external meter:",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

        # Show current input with decimal separator (XX.XX format)
        if self.sqm_input:
            if len(self.sqm_input) <= 2:
                # Show what we have so far
                display = self.sqm_input + "_" * (2 - len(self.sqm_input)) + "." + "__"
            else:
                # Insert decimal point after 2 digits
                display = (
                    self.sqm_input[:2]
                    + "."
                    + self.sqm_input[2:]
                    + "_" * (4 - len(self.sqm_input))
                )
        else:
            display = "__.__"

        self.draw.text(
            (10, 65),
            f"SQM: {display}",
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )

        # Legend
        self.draw.text(
            (10, 95),
            "0-9: Enter  -: Del",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        self.draw.text(
            (10, 107),
            f"{self._SQUARE_}: OK  0: Skip",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    def _draw_confirm(self):
        """Draw confirmation screen"""
        self.draw.text(
            (10, 20),
            "READY?",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        if self.reference_sqm:
            self.draw.text(
                (10, 45),
                f"Ref SQM: {self.reference_sqm:.2f}",
                font=self.fonts.base.font,
                fill=self.colors.get(192),
            )
        else:
            self.draw.text(
                (10, 45),
                "No reference SQM",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )

        self.draw.text(
            (10, 65),
            "20 images",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )
        self.draw.text(
            (10, 77),
            "~1 minute",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

        # Legend
        self.draw.text(
            (10, 110),
            f"{self._SQUARE_}: START  0: CANCEL",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    def _draw_capturing(self):
        """Draw capture progress"""
        if not self.sweep_started:
            # Start sweep
            self.sweep_started = True
            self.start_time = time.time()
            # Send command with reference SQM
            cmd = (
                f"capture_exp_sweep:{self.reference_sqm if self.reference_sqm else 0.0}"
            )
            self.command_queues["camera"].put(cmd)
            # Wait a moment for sweep directory to be created
            time.sleep(0.2)

        self.draw.text(
            (10, 15),
            "CAPTURING...",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        # Count files in sweep directory that was created after we started
        file_count = self._get_sweep_files_since_start()
        progress_pct = min(100, int((file_count / self.total_images) * 100))

        # Show actual file count
        self.draw.text(
            (10, 40),
            f"{file_count} / {self.total_images}",
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )

        # Progress bar
        bar_x = 10
        bar_y = 65
        bar_width = 108
        bar_height = 12

        self.draw.rectangle(
            [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
            outline=self.colors.get(128),
            fill=self.colors.get(0),
        )

        filled_width = int(bar_width * (progress_pct / 100))
        self.draw.rectangle(
            [bar_x, bar_y, bar_x + filled_width, bar_y + bar_height],
            fill=self.colors.get(128),
        )

        # Estimated time remaining based on actual progress
        elapsed = int(time.time() - self.start_time)
        if file_count > 0:
            avg_time_per_image = elapsed / file_count
            remaining = int(avg_time_per_image * (self.total_images - file_count))
        else:
            remaining = self.estimated_duration

        mins = remaining // 60
        secs = remaining % 60
        self.draw.text(
            (10, 85),
            f"~{mins}:{secs:02d} remaining",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )

        # Auto-complete when all files captured
        if file_count >= self.total_images:
            self._add_detailed_metadata()
            self.state = SweepState.COMPLETE

    def _get_sweep_files_since_start(self):
        """Count PNG files in sweep directory created after we started"""
        try:
            captures_dir = Path(utils.data_dir) / "captures"
            if not captures_dir.exists():
                return 0

            # Find sweep directories created after we started (with tolerance)
            sweep_dirs = []
            for sweep_dir in captures_dir.glob("sweep_*"):
                # Check if directory was created after we started (minus 1 second tolerance)
                if sweep_dir.stat().st_ctime >= (self.start_time - 1):
                    sweep_dirs.append(sweep_dir)

            if not sweep_dirs:
                return 0

            # Use the most recent one (should be ours)
            most_recent_sweep = max(sweep_dirs, key=lambda p: p.stat().st_ctime)

            # Count processed PNG files (the ones we care about for progress)
            png_files = list(most_recent_sweep.glob("*_processed.png"))
            return len(png_files)
        except Exception:
            # If anything fails, return 0 to avoid crashing the UI
            return 0

    def _add_detailed_metadata(self):
        """Add detailed metadata including SQM state and NoiseFloorEstimator output."""
        try:
            from PiFinder.sqm.noise_floor import NoiseFloorEstimator

            # Find the sweep directory
            captures_dir = Path(utils.data_dir) / "captures"
            sweep_dirs = [
                d for d in captures_dir.glob("sweep_*")
                if d.stat().st_ctime >= (self.start_time - 1)
            ]
            if not sweep_dirs:
                logger.warning("No sweep directory found for metadata update")
                return

            sweep_dir = max(sweep_dirs, key=lambda p: p.stat().st_ctime)
            metadata_file = sweep_dir / "sweep_metadata.json"

            if not metadata_file.exists():
                logger.warning(f"No metadata file found at {metadata_file}")
                return

            # Load existing metadata
            with open(metadata_file, "r") as f:
                metadata = json.load(f)

            # Add current SQM state (like sqm_correction does)
            sqm_state = self.shared_state.sqm()
            if sqm_state:
                metadata["sqm"] = {
                    "pifinder_value": sqm_state.value,
                    "reference_value": self.reference_sqm,
                    "difference": (self.reference_sqm - sqm_state.value)
                                  if self.reference_sqm and sqm_state.value else None,
                    "source": sqm_state.source,
                }

            # Add full SQM calculation details
            sqm_details = self.shared_state.sqm_details()
            if sqm_details:
                metadata["sqm_calculation"] = sqm_details

            # Add image metadata
            image_metadata = self.shared_state.last_image_metadata()
            if image_metadata:
                metadata["image"] = {
                    "exposure_us": image_metadata.get("exposure_time"),
                    "exposure_sec": image_metadata.get("exposure_time", 0) / 1_000_000.0,
                    "gain": image_metadata.get("gain"),
                    "imu_delta": image_metadata.get("imu_delta"),
                }

            # Add solve data
            solution = self.shared_state.solution()
            if solution:
                metadata["solve"] = {
                    "ra_deg": solution.get("RA"),
                    "dec_deg": solution.get("Dec"),
                    "altitude_deg": solution.get("Alt"),
                    "azimuth_deg": solution.get("Az"),
                    "fov_deg": solution.get("FOV"),
                    "matches": solution.get("Matches"),
                    "rmse": solution.get("RMSE"),
                }

            # Add NoiseFloorEstimator output
            camera_type = self.shared_state.camera_type()
            camera_type_processed = f"{camera_type}_processed"
            exposure_sec = (image_metadata.get("exposure_time", 500000) / 1_000_000.0
                          if image_metadata else 0.5)

            if self.camera_image is not None:
                image_array = np.array(self.camera_image.convert("L"))

                estimator = NoiseFloorEstimator(
                    camera_type=camera_type_processed,
                    enable_zero_sec_sampling=False,
                )
                _, nf_details = estimator.estimate_noise_floor(
                    image=image_array,
                    exposure_sec=exposure_sec,
                )

                nf_details.pop("request_zero_sec_sample", None)
                nf_details["camera_type"] = camera_type_processed
                metadata["noise_floor_estimator"] = nf_details

            # Save updated metadata
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"Added detailed metadata to {metadata_file}")

        except Exception as e:
            logger.error(f"Failed to add detailed metadata: {e}")

    def _draw_complete(self):
        """Draw completion screen"""
        self.draw.text(
            (10, 40),
            "SWEEP COMPLETE!",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        self.draw.text(
            (10, 70),
            "Metadata saved",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

        self.draw.text(
            (10, 110),
            f"{self._SQUARE_}: EXIT",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

    # Key handlers
    def key_number(self, number):
        """Handle number keys"""
        if self.state == SweepState.ASK_SQM:
            if number == 0 and self.sqm_input == "":
                # Skip SQM input
                self.state = SweepState.CONFIRM
            elif len(self.sqm_input) < 4:  # Limit to 4 digits (XX.XX)
                self.sqm_input += str(number)
        elif self.state == SweepState.CONFIRM:
            if number == 0:
                # Cancel
                if self.remove_from_stack:
                    self.remove_from_stack()

    def key_minus(self):
        """Handle minus button - delete last digit"""
        if self.state == SweepState.ASK_SQM:
            if self.sqm_input:
                self.sqm_input = self.sqm_input[:-1]

    def key_square(self):
        """Handle square button"""
        if self.state == SweepState.ASK_SQM:
            # Accept SQM input and move to confirm
            if self.sqm_input and len(self.sqm_input) == 4:
                # Convert to XX.XX format
                try:
                    self.reference_sqm = float(
                        self.sqm_input[:2] + "." + self.sqm_input[2:]
                    )
                    self.state = SweepState.CONFIRM
                except ValueError:
                    # Invalid input, clear and try again
                    self.sqm_input = ""
            elif not self.sqm_input:
                # No input, skip to confirm
                self.state = SweepState.CONFIRM
        elif self.state == SweepState.CONFIRM:
            # Start capture
            self.state = SweepState.CAPTURING
        elif self.state == SweepState.COMPLETE:
            # Exit
            if self.remove_from_stack:
                self.remove_from_stack()
