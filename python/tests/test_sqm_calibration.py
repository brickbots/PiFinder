import numpy as np
import pytest

from PiFinder.ui.sqm_calibration import UISQMCalibration


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
