from types import SimpleNamespace

import numpy as np
import pytest

from PiFinder.ui.sqm_calibration import UISQMCalibration


class _CameraSim:
    """Delivers one queued metadata frame per 'capture' command."""

    def __init__(self, deliveries):
        self.deliveries = list(deliveries)
        self.current = {"exposure_end": 0.0}
        self.captures = 0

    def put(self, cmd):
        if cmd == "capture":
            if self.captures < len(self.deliveries):
                self.current = self.deliveries[self.captures]
            self.captures += 1

    def last_image_metadata(self):
        return self.current


def _bare_wizard(sim):
    ui = UISQMCalibration.__new__(UISQMCalibration)
    ui.shared_state = SimpleNamespace(last_image_metadata=sim.last_image_metadata)
    ui.command_queues = {"camera": sim}
    return ui


@pytest.mark.unit
class TestSQMCalibrationAnalysis:
    def test_dark_current_fit_uses_multiple_exposures(self):
        bias = 200.0
        rate = 4.5
        exposures = [0.05, 0.1, 0.2, 0.4]
        frames = [
            np.full((8, 8), bias + rate * exposure, dtype=np.float64)
            for exposure in exposures
        ]

        fitted = UISQMCalibration._fit_dark_current_rate(frames, exposures, bias)

        assert fitted == pytest.approx(rate)

    def test_dark_current_fit_rejects_mismatched_frames_and_times(self):
        with pytest.raises(ValueError, match="matching"):
            UISQMCalibration._fit_dark_current_rate(
                [np.zeros((2, 2)), np.zeros((2, 2))],
                [0.1],
                0.0,
            )

    def test_dark_current_fit_never_publishes_negative_rate(self):
        frames = [np.full((4, 4), 99.0), np.full((4, 4), 98.0)]

        fitted = UISQMCalibration._fit_dark_current_rate(
            frames, [0.1, 0.2], bias_offset=100.0
        )

        assert fitted == 0.0


@pytest.mark.unit
class TestCaptureAndWait:
    def test_accepts_frame_at_requested_exposure(self):
        sim = _CameraSim([{"exposure_end": 1.0, "actual_exposure_us": 29}])
        ui = _bare_wizard(sim)
        assert ui._capture_and_wait(1) == 1.0
        assert sim.captures == 1

    def test_stale_exposure_frame_triggers_recapture(self):
        # First frames after an exposure change still carry the previous
        # exposure; actual_exposure_us exposes it while exposure_time echoes
        # the committed setting.
        sim = _CameraSim(
            [
                {"exposure_end": 1.0, "actual_exposure_us": 999999, "exposure_time": 1},
                {"exposure_end": 2.0, "actual_exposure_us": 999999, "exposure_time": 1},
                {"exposure_end": 3.0, "actual_exposure_us": 29, "exposure_time": 1},
            ]
        )
        ui = _bare_wizard(sim)
        assert ui._capture_and_wait(1) == 3.0
        assert sim.captures == 3

    def test_falls_back_to_exposure_time_without_actual(self):
        sim = _CameraSim([{"exposure_end": 1.0, "exposure_time": 500}])
        ui = _bare_wizard(sim)
        assert ui._capture_and_wait(500) == 1.0

    def test_tolerance_scales_with_exposure(self):
        # 1s request delivered at 999999us (driver rounding) must pass.
        sim = _CameraSim([{"exposure_end": 1.0, "actual_exposure_us": 999999}])
        ui = _bare_wizard(sim)
        assert ui._capture_and_wait(1_000_000) == 1.0

    def test_discard_clamp_settle_frames_burns_frames(self):
        sim = _CameraSim(
            [{"exposure_end": float(i), "actual_exposure_us": 29} for i in (1, 2, 3)]
        )
        ui = _bare_wizard(sim)
        ui._discard_clamp_settle_frames(1)
        assert sim.captures == UISQMCalibration.CLAMP_SETTLE_DISCARD_FRAMES
