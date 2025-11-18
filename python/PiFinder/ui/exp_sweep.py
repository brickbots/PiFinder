#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Exposure Sweep UI

Multi-step wizard for capturing exposure sweeps with reference SQM.
"""

import time
from enum import Enum
from pathlib import Path
from PiFinder import utils
from PiFinder.ui.base import UIModule


class SweepState(Enum):
    """Sweep wizard states"""
    ASK_SQM = "ask_sqm"  # Ask for reference SQM value
    CONFIRM = "confirm"  # Confirm ready to start
    CAPTURING = "capturing"  # Capturing sweep
    COMPLETE = "complete"  # Sweep done


class UIExpSweep(UIModule):
    """
    Exposure Sweep Wizard

    Steps:
    1. Ask user for reference SQM value from external meter
    2. Confirm ready to start
    3. Capture 100 image sweep
    4. Save metadata and exit
    """

    __title__ = "EXP SWEEP"
    __help_name__ = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = SweepState.ASK_SQM
        self.reference_sqm = None
        self.sqm_input = ""  # User input for SQM value
        self.sweep_started = False
        self.start_time = None
        self.total_images = 100  # Expected number of images
        self.estimated_duration = 240  # 4 minutes estimated

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

        # Show current input
        input_text = self.sqm_input if self.sqm_input else "_"
        self.draw.text(
            (10, 65),
            f"SQM: {input_text}",
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )

        # Legend
        self.draw.text(
            (10, 95),
            "0-9: Enter",
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
            "100 images",
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )
        self.draw.text(
            (10, 77),
            "~4 minutes",
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
            cmd = f"capture_exp_sweep:{self.reference_sqm if self.reference_sqm else 0.0}"
            self.command_queues["camera"].put(cmd)

        self.draw.text(
            (10, 15),
            "CAPTURING...",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        # Count actual files in sweep directory
        file_count = self._count_sweep_files()
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
            self.state = SweepState.COMPLETE

    def _count_sweep_files(self):
        """Count PNG files in most recent sweep directory"""
        try:
            captures_dir = Path(utils.data_dir) / "captures"
            if not captures_dir.exists():
                return 0

            # Find most recent sweep directory
            sweep_dirs = sorted(captures_dir.glob("sweep_*"), key=lambda p: p.name, reverse=True)
            if not sweep_dirs:
                return 0

            most_recent_sweep = sweep_dirs[0]
            # Count processed PNG files (the ones we care about for progress)
            png_files = list(most_recent_sweep.glob("*_processed.png"))
            return len(png_files)
        except Exception:
            # If anything fails, return 0 to avoid crashing the UI
            return 0

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
            elif len(self.sqm_input) < 5:  # Limit input length
                self.sqm_input += str(number)
        elif self.state == SweepState.CONFIRM:
            if number == 0:
                # Cancel
                if self.remove_from_stack:
                    self.remove_from_stack()

    def key_square(self):
        """Handle square button"""
        if self.state == SweepState.ASK_SQM:
            # Accept SQM input and move to confirm
            if self.sqm_input:
                try:
                    self.reference_sqm = float(self.sqm_input)
                    self.state = SweepState.CONFIRM
                except ValueError:
                    # Invalid input, clear and try again
                    self.sqm_input = ""
            else:
                # No input, skip to confirm
                self.state = SweepState.CONFIRM
        elif self.state == SweepState.CONFIRM:
            # Start capture
            self.state = SweepState.CAPTURING
        elif self.state == SweepState.COMPLETE:
            # Exit
            if self.remove_from_stack:
                self.remove_from_stack()
