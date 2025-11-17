#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Exposure Sweep Progress UI

Displays real-time progress during exposure sweep capture.
"""

import time
import queue
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
        self.progress_text = "Starting sweep..."
        self.sweep_started = False
        self.sweep_complete = False
        self.start_time = time.time()

        # Send command to camera to start sweep
        self.command_queues["camera"].put("capture_exp_sweep")
        self.update(force=True)

    def update(self, force=False):
        """Update display with current progress"""
        # Check console queue for progress messages
        try:
            while True:
                console_msg = self.console_queue.get(block=False)

                # Look for camera sweep messages
                if console_msg.startswith("CAM: "):
                    cam_msg = console_msg[5:]  # Strip "CAM: " prefix

                    if "Sweep" in cam_msg:
                        self.progress_text = cam_msg
                        self.sweep_started = True

                        if "done" in cam_msg.lower():
                            self.sweep_complete = True
                    elif "Starting sweep" in cam_msg:
                        self.progress_text = "Starting..."
                        self.sweep_started = True
                else:
                    # Put non-camera messages back for main loop to handle
                    # (But for now just ignore them to avoid queue issues)
                    pass

        except queue.Empty:
            pass

        # Auto-exit when complete
        if self.sweep_complete:
            time.sleep(0.5)  # Brief pause to show "done" message
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

        # Progress text (e.g., "Sweep 23/100")
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
                f"Elapsed: {elapsed}s",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )

        # Instructions
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
