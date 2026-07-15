"""
SQM Correct: set a session correction from a hand-held reference meter.

The PiFinder SQM is stable within a night but its absolute scale depends on
the night's sky spectrum through the per-sensor band offset (see
CameraProfile.sqm_band_offset -- calibrated for one sky regime). Aiming a
reference meter at the camera's field and entering its reading corrects the
whole session to tonight's actual sky: every subsequent reading is shifted by
``delta = reference - current``.

The correction lives in shared state only (resets on restart -- tonight's
spectrum is tonight's) and every correction event is appended to
``~/PiFinder_data/sqm_corrects.jsonl``, building the per-site calibration
dataset as a side effect of normal use.
"""

import json
import logging
from enum import Enum
from typing import Any, TYPE_CHECKING

from PiFinder import timez, utils
from PiFinder.ui.base import UIModule

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


logger = logging.getLogger("UI.SQMCorrect")


class CorrectState(Enum):
    ASK = "ask"  # entering the meter reading
    DONE = "done"  # correction applied, showing result


class UISQMCorrect(UIModule):
    """Enter a reference-meter reading to correct the session's SQM scale."""

    __title__ = "SQM CORRECT"
    __help_name__ = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = CorrectState.ASK
        self.sqm_input = ""
        self.applied_delta = None

    def active(self):
        self.state = CorrectState.ASK
        self.sqm_input = ""
        # Keep the stable SNR auto-exposure the SQM screen uses
        self.command_queues["camera"].put("set_ae_mode:snr")
        self.update(force=True)

    def inactive(self):
        self.command_queues["camera"].put("set_ae_mode:pid")

    def _current_sqm(self):
        sqm_state = self.shared_state.sqm()
        if sqm_state.last_update is None or sqm_state.value is None:
            return None
        return sqm_state.value

    def update(self, force=False):
        self.clear_screen()
        tb = self.display_class.titlebar_height
        base_h = self.fonts.base.height
        left = 10
        y = tb + 3

        current = self._current_sqm()
        old_delta = self.shared_state.sqm_correct_delta()

        if self.state == CorrectState.ASK:
            self.draw.text(
                (left, y),
                _("METER SQM"),
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            y += self.fonts.bold.height + 4
            if current is not None:
                self.draw.text(
                    (left, y),
                    _("PiFinder: {v:.2f}").format(v=current),
                    font=self.fonts.base.font,
                    fill=self.colors.get(128),
                )
            else:
                self.draw.text(
                    (left, y),
                    _("NO SQM DATA YET"),
                    font=self.fonts.base.font,
                    fill=self.colors.get(128),
                )
            y += base_h + 2

            if current is None:
                # Correcting needs a live reading to offset against; there is
                # nothing to enter until the SQM has a value.
                self.draw.text(
                    (left, y),
                    _("wait for a solve"),
                    font=self.fonts.base.font,
                    fill=self.colors.get(128),
                )
                y = self.display_class.resY - base_h - 7
                self.draw.text(
                    (left, y),
                    f"{self._SQUARE_}: " + _("EXIT"),
                    font=self.fonts.base.font,
                    fill=self.colors.get(128),
                )
                return self.screen_update(title_bar=True)

            if old_delta:
                self.draw.text(
                    (left, y),
                    _("correct now: {d:+.2f}").format(d=old_delta),
                    font=self.fonts.base.font,
                    fill=self.colors.get(64),
                )
                y += base_h
            y += 4

            # Entry field, XX.XX
            if len(self.sqm_input) <= 2:
                display = self.sqm_input + "_" * (2 - len(self.sqm_input)) + ".__"
            else:
                display = (
                    self.sqm_input[:2]
                    + "."
                    + self.sqm_input[2:]
                    + "_" * (4 - len(self.sqm_input))
                )
            self.draw.text(
                (left, y),
                display,
                font=self.fonts.huge.font,
                fill=self.colors.get(192),
            )
            y = self.display_class.resY - 2 * base_h - 7
            self.draw.text(
                (left, y),
                _("0: clear  -: del"),
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            y += base_h + 2
            self.draw.text(
                (left, y),
                f"{self._SQUARE_}: " + _("SET"),
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )

        elif self.state == CorrectState.DONE:
            self.draw.text(
                (left, y),
                _("CORRECTED"),
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            y += self.fonts.bold.height + 6
            if self.applied_delta is not None:
                self.draw.text(
                    (left, y),
                    _("delta {d:+.2f}").format(d=self.applied_delta),
                    font=self.fonts.large.font,
                    fill=self.colors.get(192),
                )
            y = self.display_class.resY - base_h - 7
            self.draw.text(
                (left, y),
                f"{self._SQUARE_}: " + _("EXIT"),
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )

        return self.screen_update(title_bar=True)

    def _log_correct(self, reference, measured, old_delta, new_delta):
        """Append the correction event to the calibration dataset."""
        try:
            record = {
                "timestamp": timez.local_now().isoformat(),
                "reference_sqm": reference,
                "pifinder_sqm": measured,
                "old_delta": old_delta,
                "new_delta": new_delta,
                "camera_type": self.shared_state.camera_type(),
            }
            details = self.shared_state.sqm_details()
            if details:
                for k in ("sqm_band_offset", "mzero_correction", "n_matched_stars"):
                    if k in details:
                        record[k] = details[k]
            location = self.shared_state.location()
            if location:
                record["lat"] = round(location.lat, 3)
                record["lon"] = round(location.lon, 3)
            path = utils.data_dir / "sqm_corrects.jsonl"
            with open(path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.warning(f"Could not log correct event: {e}")

    def _set_correct(self, reference):
        current = self._current_sqm()
        if current is None:
            return False
        old_delta = self.shared_state.sqm_correct_delta()
        # `current` already includes the old delta; the new total delta
        # re-corrects directly onto the fresh reference.
        new_delta = old_delta + (reference - current)
        self.shared_state.set_sqm_correct_delta(new_delta)
        self._log_correct(reference, current, old_delta, new_delta)
        logger.info(
            f"SQM correct set: ref={reference:.2f} measured={current:.2f} "
            f"delta={new_delta:+.2f}"
        )
        self.applied_delta = new_delta
        return True

    # Key handlers
    def key_number(self, number):
        if self.state != CorrectState.ASK:
            return
        if self._current_sqm() is None:
            return
        if number == 0 and self.sqm_input == "":
            # Clear any existing correction
            self.shared_state.set_sqm_correct_delta(0.0)
            self.applied_delta = 0.0
            self.state = CorrectState.DONE
        elif len(self.sqm_input) < 4:
            self.sqm_input += str(number)

    def key_minus(self):
        if self.state == CorrectState.ASK and self.sqm_input:
            self.sqm_input = self.sqm_input[:-1]

    def key_square(self):
        if self.state == CorrectState.ASK:
            if self._current_sqm() is None:
                # No reading to correct against; square just exits.
                if self.remove_from_stack:
                    self.remove_from_stack()
                return
            if len(self.sqm_input) == 4:
                try:
                    reference = float(self.sqm_input[:2] + "." + self.sqm_input[2:])
                except ValueError:
                    self.sqm_input = ""
                    return
                if self._set_correct(reference):
                    self.state = CorrectState.DONE
                else:
                    self.sqm_input = ""
        elif self.state == CorrectState.DONE:
            if self.remove_from_stack:
                self.remove_from_stack()
