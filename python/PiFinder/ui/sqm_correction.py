"""
SQM Correction UI - Allows user to manually correct SQM values
and save correction data packages for calibration validation.
"""

import os
import json
import time
import zipfile
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, TYPE_CHECKING
from PIL import Image
import numpy as np

from PiFinder.ui.base import UIModule
from PiFinder.ui.numeric_entry import (
    NumericEntryField,
    EntryLegend,
    LegendItem,
    BlinkingCursor,
)
from PiFinder import utils

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


logger = logging.getLogger("PiFinder.SQMCorrection")


class UISQMCorrection(UIModule):
    """
    UI for correcting SQM values and creating calibration packages.

    User enters a corrected SQM value, and the system creates a zip file containing:
    - Raw 16-bit TIFF image
    - Processed 8-bit PNG image
    - JSON metadata with original/corrected SQM, GPS location, solve data, etc.
    """

    __title__ = _("SQM Correction")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Get current SQM from shared state
        sqm_state = self.shared_state.sqm()
        self.original_sqm = sqm_state.value if sqm_state.value else 18.0

        # Initialize numeric entry field with XX.XX format for SQM values
        self.entry_field = NumericEntryField(
            format_pattern="XX.XX",
            validation_range=(10.0, 23.0),
            placeholder_char="_",
        )

        # Initialize blinking cursor
        self.cursor = BlinkingCursor(blink_interval=0.5)

        # Initialize legend with proper icons (copied from radec_entry.py)
        back_icon = ""
        go_icon = ""

        self.legend = EntryLegend(
            items=[
                LegendItem(icon=back_icon, label=_("Cancel")),  # left arrow
                LegendItem(icon=go_icon, label=_("Save")),  # right arrow
                LegendItem(icon="- ", label=_("Del")),  # minus with space
            ],
            show_separator=True,
            layout="single_line",
        )

        self.error_message = None
        self.success_message = None
        self.message_time = None

    def update(self, force=False):
        """Draw the correction UI"""
        self.clear_screen()

        # Title
        title = _("SQM Correction")
        self.draw.text(
            (0, 5),
            title,
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )

        # Show original SQM value
        original_text = _("Original: {sqm:.2f}").format(sqm=self.original_sqm)
        self.draw.text(
            (0, 25),
            original_text,
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )

        # Show correction input label
        corrected_label = _("Corrected:")
        self.draw.text(
            (0, 45),
            corrected_label,
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )

        # Calculate centered position for entry field
        entry_y = 60
        char_width = self.fonts.large.width
        total_width = char_width * len(self.entry_field.positions)
        entry_x = (128 - total_width) // 2

        # Draw numeric entry field using component with blinking cursor
        self.entry_field.draw(
            draw=self.draw,
            screen=self.screen,
            x=entry_x,
            y=entry_y,
            font=self.fonts.large.font,
            char_width=char_width,
            char_height=self.fonts.large.height,
            normal_color=self.colors.get(255),
            blinking_cursor=self.cursor,
        )

        # Show error or success message
        message_y = 85
        if self.error_message and self.message_time:
            # Show error for 3 seconds
            if (datetime.now() - self.message_time).total_seconds() < 3:
                self.draw.text(
                    (0, message_y),
                    self.error_message,
                    font=self.fonts.base.font,
                    fill=self.colors.get(255),
                )
            else:
                self.error_message = None
                self.message_time = None

        if self.success_message and self.message_time:
            # Show success for 3 seconds, then exit
            if (datetime.now() - self.message_time).total_seconds() < 3:
                self.draw.text(
                    (0, message_y),
                    self.success_message,
                    font=self.fonts.base.font,
                    fill=self.colors.get(255),
                )
            else:
                # Auto-exit after showing success message
                if self.remove_from_stack:
                    self.remove_from_stack()

        # Draw legend at bottom using component
        self.legend.draw(
            draw=self.draw,
            screen_width=128,
            screen_height=128,
            font=self.fonts.base.font,
            font_height=self.fonts.base.height,
            separator_color=self.colors.get(128),
            text_color=self.colors.get(128),
            margin=2,
        )

        return self.screen_update()

    def key_number(self, number):
        """Handle number key input"""
        self.entry_field.insert_digit(number)

    def key_0(self):
        """Handle 0 key"""
        self.entry_field.insert_digit(0)

    def key_plus(self):
        """Delete - remove digit at cursor"""
        self.entry_field.delete_digit()

    def key_minus(self):
        """Delete - remove digit at cursor"""
        self.entry_field.delete_digit()

    def key_left(self):
        """Cancel and exit"""
        if self.remove_from_stack:
            self.remove_from_stack()

    def key_right(self):
        """Save correction package"""
        # Validate input using entry field component
        is_valid, corrected_sqm = self.entry_field.validate()

        if not is_valid:
            if corrected_sqm is None:
                self.error_message = _("Enter a value")
            else:
                self.error_message = _("Range: 10-23")
            self.message_time = datetime.now()
            return

        # Show saving message and force screen update
        self.success_message = _("Saving...")
        self.message_time = datetime.now()
        self.update(force=True)

        # Create correction package
        try:
            zip_path = self._create_correction_package(corrected_sqm)
            self.success_message = _("Saved: {filename}").format(
                filename=os.path.basename(zip_path)
            )
            self.message_time = datetime.now()
            logger.info(f"SQM correction package saved: {zip_path}")
        except Exception as e:
            logger.error(f"Failed to create correction package: {e}")
            self.error_message = _("Save failed")
            self.message_time = datetime.now()

    def _wait_for_exposure(self, target_exp_us: int, timeout: float = 5.0) -> bool:
        """Wait for camera to capture image at target exposure."""
        start = time.time()
        while time.time() - start < timeout:
            metadata = self.shared_state.last_image_metadata()
            if metadata and abs(metadata.get("exposure_time", 0) - target_exp_us) < 1000:
                # Wait one more frame for image to be ready
                time.sleep(0.3)
                return True
            time.sleep(0.1)
        return False

    def _capture_at_exposure(
        self, exp_us: int, corrections_dir: Path, timestamp: str, label: str
    ) -> Dict[str, Any]:
        """Capture image at specific exposure and return file info."""
        # Set exposure
        self.command_queues["camera"].put(f"set_exp:{exp_us}")

        # Wait for image at this exposure
        if not self._wait_for_exposure(exp_us):
            logger.warning(f"Timeout waiting for exposure {exp_us}µs")
            return {}

        # Capture images
        camera_image = self.camera_image.copy()
        raw_image = self.shared_state.cam_raw()

        files: Dict[str, Any] = {}

        # Save processed PNG
        processed_path = f"correction_{timestamp}_{label}_processed.png"
        camera_image.save(str(corrections_dir / processed_path))
        files["processed"] = processed_path

        # Save raw TIFF if available
        if raw_image is not None:
            raw_path = f"correction_{timestamp}_{label}_raw.tiff"
            raw_image_pil = Image.fromarray(np.asarray(raw_image, dtype=np.uint16))
            raw_image_pil.save(str(corrections_dir / raw_path))
            files["raw"] = raw_path

        files["exposure_us"] = exp_us
        return files

    def _create_correction_package(self, corrected_sqm: float) -> str:
        """
        Create a zip file containing correction data with bracketed exposures.

        Captures 3 exposures: current, +1 stop (2x), -1 stop (0.5x)
        If +1 stop exceeds max (1s), captures -2 stops instead.

        Returns:
            Path to created zip file
        """
        # Create corrections directory
        corrections_dir = Path(utils.data_dir) / "captures" / "sqm_corrections"
        corrections_dir.mkdir(parents=True, exist_ok=True)

        # Generate timestamp for filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"sqm_correction_{timestamp}.zip"
        zip_path = corrections_dir / zip_filename

        # Get current exposure
        image_metadata = self.shared_state.last_image_metadata()
        current_exp = image_metadata.get("exposure_time", 500000) if image_metadata else 500000

        # Calculate bracket exposures (in microseconds)
        max_exp = 1000000  # 1 second max
        min_exp = 10000    # 10ms min

        exp_above = min(current_exp * 2, max_exp)
        exp_below = max(current_exp // 2, min_exp)
        exp_below2 = max(current_exp // 4, min_exp)

        # Determine which 3 exposures to capture
        if exp_above <= current_exp:
            # Can't go above, use current and two below
            exposures = [
                (current_exp, "base"),
                (exp_below, "minus1"),
                (exp_below2, "minus2"),
            ]
        else:
            # Normal bracket: below, current, above
            exposures = [
                (exp_below, "minus1"),
                (current_exp, "base"),
                (exp_above, "plus1"),
            ]

        # Collect metadata first (before changing exposure)
        metadata = self._collect_metadata(corrected_sqm)
        metadata["bracket_exposures"] = []

        # Capture all bracketed exposures
        all_files = []
        for exp_us, label in exposures:
            # Update saving message
            self.success_message = _("Saving {label}...").format(label=label)
            self.update(force=True)

            files = self._capture_at_exposure(exp_us, corrections_dir, timestamp, label)
            if files:
                all_files.append(files)
                metadata["bracket_exposures"].append({
                    "label": label,
                    "exposure_us": exp_us,
                    "exposure_sec": exp_us / 1_000_000.0,
                })

        # Re-enable auto-exposure
        self.command_queues["camera"].put("set_exp:auto")

        # Create zip file
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add all captured images
            for files in all_files:
                if "processed" in files:
                    zf.write(corrections_dir / files["processed"], arcname=files["processed"])
                    (corrections_dir / files["processed"]).unlink()
                if "raw" in files:
                    zf.write(corrections_dir / files["raw"], arcname=files["raw"])
                    (corrections_dir / files["raw"]).unlink()

            # Add metadata JSON
            metadata_path = f"correction_{timestamp}_metadata.json"
            with open(corrections_dir / metadata_path, "w") as f:
                json.dump(metadata, f, indent=2, default=str)
            zf.write(corrections_dir / metadata_path, arcname=metadata_path)
            (corrections_dir / metadata_path).unlink()

        return str(zip_path)

    def _collect_metadata(self, corrected_sqm: float) -> Dict[str, Any]:
        """Collect all relevant metadata for the correction package"""
        metadata: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "sqm": {
                "original": self.original_sqm,
                "corrected": corrected_sqm,
                "difference": corrected_sqm - self.original_sqm,
            },
        }

        # Get SQM source
        sqm_state = self.shared_state.sqm()
        if sqm_state.source:
            metadata["sqm"]["source"] = sqm_state.source

        # Get GPS location
        location = self.shared_state.location()
        if location and location.lock:
            metadata["location"] = {
                "latitude": location.lat,
                "longitude": location.lon,
                "altitude_m": location.altitude,
                "timezone": location.timezone,
            }

        # Get GPS datetime
        gps_datetime = self.shared_state.datetime()
        if gps_datetime:
            metadata["gps_datetime"] = gps_datetime.isoformat()

        # Get solve data (RA/Dec/Alt/Az)
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

        # Get image metadata (exposure, gain, etc.)
        image_metadata = self.shared_state.last_image_metadata()
        if image_metadata:
            metadata["image"] = {
                "exposure_us": image_metadata.get("exposure_time"),
                "exposure_sec": image_metadata.get("exposure_time", 0) / 1_000_000.0,
                "gain": image_metadata.get("gain"),
                "imu_delta": image_metadata.get("imu_delta"),
            }

        # Get camera type
        metadata["camera_type"] = self.shared_state.camera_type()

        # Get adaptive noise floor (used for auto-exposure and SQM pedestal)
        metadata["noise_floor_adu"] = self.shared_state.noise_floor()

        # Get full SQM calculation details (mzero, background, extinction, etc.)
        sqm_details = self.shared_state.sqm_details()
        if sqm_details:
            metadata["sqm_calculation"] = sqm_details

        return metadata

    def active(self):
        """Called when module becomes active"""
        pass
