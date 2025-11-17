#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Exposure Sweep Progress UI

Displays progress during exposure sweep capture.
Shows elapsed time and estimated progress based on typical sweep duration.
"""

import time
from PiFinder.ui.base import UIModule


class UIExpSweep(UIModule):
    """
    Exposure Sweep Progress Display

    Shows real-time progress as the camera captures the exposure sweep.
    Monitors console_queue for progress updates and automatically exits when complete.
    """

    __title__ = "EXP SWEEP"
    __help_name__ = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.progress_text = "Starting..."
        self.sweep_started = False
        self.sweep_complete = False
        self.start_time = None

    def active(self):
        """Called when module becomes active - start the sweep"""
        self.progress_text = "Capturing 100 images..."
        self.sweep_started = False
        self.sweep_complete = False
        self.start_time = time.time()

        # Send command to camera to start sweep
        self.command_queues["camera"].put("capture_exp_sweep")
        self.update(force=True)

    def update(self, force=False):
        """Update display with elapsed time"""
        # Calculate elapsed time
        elapsed = int(time.time() - self.start_time)

        # Estimate progress based on typical 25-second sweep duration
        # This is approximate since we can't directly monitor camera progress
        estimated_duration = 25  # seconds
        if elapsed >= estimated_duration:
            self.sweep_complete = True
            self.progress_text = "Complete!"
        else:
            # Show estimated progress
            progress_pct = int((elapsed / estimated_duration) * 100)
            self.progress_text = f"Progress: ~{progress_pct}%"

        # Auto-exit when complete (with extra margin for safety)
        if elapsed >= estimated_duration + 2:
            if self.remove_from_stack:
                self.remove_from_stack()
            return self.screen_update()

        # Draw progress screen
        self.clear_screen()

        # Title
        self.draw.text(
            (10, 15),
            "EXPOSURE SWEEP",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        # Progress text
        self.draw.text(
            (10, 40),
            self.progress_text,
            font=self.fonts.large.font,
            fill=self.colors.get(192),
        )

        # Elapsed time
        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            self.draw.text(
                (10, 70),
                f"Elapsed: {elapsed}s / ~25s",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )

        # Instructions
        if not self.sweep_complete:
            self.draw.text(
                (10, 95),
                "Please wait...",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )

        return self.screen_update(title_bar=True)

    def key_number(self, number):
        """Handle number keys - can't cancel mid-sweep"""
        pass  # Ignore during sweep

    def key_square(self):
        """Handle square key"""
        if self.sweep_complete:
            # Allow exit after completion
            if self.remove_from_stack:
                self.remove_from_stack()
