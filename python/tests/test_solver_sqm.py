from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from PiFinder.sqm.camera_profiles import get_camera_profile

# solver pulls in tetra3/cedar; skip these helper tests if it can't import.
solver = pytest.importorskip("PiFinder.solver")


@pytest.mark.unit
class TestExtractRawPhotometryImage:
    def test_bayer_green_channel_half_resolution(self):
        profile = get_camera_profile("imx462")  # SRGGB12
        # 4x4 RGGB mosaic: R at (0,0), G at (0,1)&(1,0), B at (1,1)
        raw = np.zeros((4, 4), dtype=np.uint16)
        raw[0::2, 1::2] = 100  # G site 1
        raw[1::2, 0::2] = 120  # G site 2
        raw[0::2, 0::2] = 999  # R (must be ignored)
        raw[1::2, 1::2] = 999  # B (must be ignored)
        green = solver._extract_raw_photometry_image(raw, profile)
        assert green.shape == (2, 2)
        assert np.allclose(green, 110.0)  # mean of the two green sites

    def test_mono_passthrough(self):
        profile = get_camera_profile("imx296")  # R10 mono
        raw = np.arange(16, dtype=np.uint16).reshape(4, 4)
        out = solver._extract_raw_photometry_image(raw, profile)
        assert out.shape == (4, 4)
        assert np.allclose(out, raw.astype(np.float32))

    def test_none_and_bad_shapes(self):
        profile = get_camera_profile("imx462")
        assert solver._extract_raw_photometry_image(None, profile) is None
        assert solver._extract_raw_photometry_image(np.zeros(5), profile) is None


@pytest.mark.unit
class TestScaleSolutionCentroids:
    def test_scales_matched_centroids(self):
        sol = {
            "FOV": 10.0,
            "matched_centroids": [[100.0, 200.0], [50.0, 60.0]],
            "matched_stars": [[1, 2, 5.0]],
            "matched_catID": [42],
        }
        scaled = solver._scale_solution_centroids(sol, 490.0 / 512.0)
        expected = np.array([[100.0, 200.0], [50.0, 60.0]]) * (490.0 / 512.0)
        assert np.allclose(scaled["matched_centroids"], expected)
        # original untouched; other fields preserved
        assert sol["matched_centroids"] == [[100.0, 200.0], [50.0, 60.0]]
        assert scaled["matched_catID"] == [42]
        assert scaled["FOV"] == 10.0


@pytest.mark.unit
class TestApplySqmCorrect:
    def test_zero_delta_is_recorded_but_not_applied(self):
        details = {"sqm_altitude_corrected": 18.5}
        v, d = solver._apply_sqm_correct(18.3, details, 0.0)
        assert v == 18.3
        assert d["sqm_altitude_corrected"] == 18.5
        assert d["sqm_correct_delta"] == 0.0

    def test_delta_shifts_value_and_altitude_corrected(self):
        details = {"sqm_altitude_corrected": 18.5}
        v, d = solver._apply_sqm_correct(18.3, details, 0.25)
        assert v == pytest.approx(18.55)
        assert d["sqm_altitude_corrected"] == pytest.approx(18.75)
        assert d["sqm_correct_delta"] == 0.25

    def test_none_value_survives(self):
        v, d = solver._apply_sqm_correct(None, {}, 0.25)
        assert v is None
        assert d["sqm_correct_delta"] == 0.25

    def test_negative_delta(self):
        v, _d = solver._apply_sqm_correct(18.3, {}, -0.4)
        assert v == pytest.approx(17.9)


@pytest.mark.unit
class TestUpdateSqmWiring:
    """update_sqm threads the pedestal override and cloud/dew guard inputs."""

    def _harness(self, monkeypatch, calibrated=False, pedestal=237.5):
        monkeypatch.setattr(
            solver,
            "_extract_raw_photometry_image",
            lambda raw, prof: np.full((300, 300), 250.0, dtype=np.float64),
        )
        shared_state = MagicMock()
        shared_state.sqm.return_value = SimpleNamespace(last_update=None, value=18.6)
        shared_state.sqm_details.return_value = {}
        shared_state.cam_raw.return_value = np.zeros((600, 600))
        shared_state.solve_image_rotation.return_value = None
        shared_state.solution.return_value = SimpleNamespace(Alt=45.0)
        shared_state.sqm_correct_delta.return_value = 0.0

        calc = MagicMock()
        calc.profile = get_camera_profile("imx462")
        calc.noise_floor_estimator.dark_current_calibrated = calibrated
        calc.calculate.return_value = (
            18.4,
            {"mzero": 10.6, "background_per_pixel": 250.0},
        )

        black_level = MagicMock()
        black_level.pedestal.return_value = pedestal
        black_level.state.return_value = (pedestal, 0.3, 20)

        cloud = MagicMock()
        cloud.add_sample.return_value = 0.05
        cloud.is_cloudy.return_value = False
        cloud.cloud_threshold = 0.25
        cloud.conditioned.return_value = True

        solution = {
            "FOV": 10.0,
            "matched_centroids": [[100.0, 200.0]],
            "matched_stars": [[1, 2, 5.0]],
            "matched_catID": [42],
        }
        return shared_state, calc, black_level, cloud, solution

    def test_threads_pedestal_and_guard(self, monkeypatch):
        shared_state, calc, black_level, cloud, solution = self._harness(monkeypatch)
        solver.update_sqm(
            shared_state=shared_state,
            sqm_calculator=calc,
            centroids=[[10.0, 10.0]],
            solution=solution,
            exposure_sec=0.5,
            altitude_deg=None,
            cloud_estimator=cloud,
            black_level_tracker=black_level,
        )
        # The tracker's pedestal is passed as the override.
        assert calc.calculate.call_args.kwargs["pedestal_override"] == 237.5
        # The independent radiometric primary reaches the guard, not the
        # star-calibrated diagnostic being evaluated.
        assert cloud.add_sample.call_args.kwargs["sky_brightness"] == 18.6
        # Feeding lives in the radiometric path; the diagnostic only consumes.
        black_level.add_sample.assert_not_called()

    def test_no_override_when_calibrated(self, monkeypatch):
        shared_state, calc, black_level, cloud, solution = self._harness(
            monkeypatch, calibrated=True
        )
        solver.update_sqm(
            shared_state=shared_state,
            sqm_calculator=calc,
            centroids=[[10.0, 10.0]],
            solution=solution,
            exposure_sec=0.5,
            altitude_deg=None,
            cloud_estimator=cloud,
            black_level_tracker=black_level,
        )
        # Wizard-measured constants are authoritative: no tracker override.
        assert calc.calculate.call_args.kwargs["pedestal_override"] is None

    def _radiometer_harness(self, calibrated=False, pedestal=237.5, cloudy=False):
        shared_state = MagicMock()
        shared_state.sqm.return_value = SimpleNamespace(last_update=None, value=18.6)
        shared_state.sqm_details.return_value = {"cloud_flag": True} if cloudy else {}
        shared_state.sqm_correct_delta.return_value = 0.0

        calc = MagicMock()
        calc.profile = get_camera_profile("imx462")
        calc.noise_floor_estimator.dark_current_calibrated = calibrated

        black_level = MagicMock()
        black_level.pedestal.return_value = pedestal
        black_level.state.return_value = (pedestal, 0.3, 20)

        sample = {
            "sequence": 7,
            "captured_at": 1000.0,
            "exposure_sec": 0.5,
            "background_per_pixel": 250.0,
            "background_mad": 1.0,
            "background_quadrants": [250.0] * 4,
            "background_gradient": 0.0,
            "sampled_pixels": 5000,
            "pixels_per_side": 490,
            "method": "sparse_central_median",
        }
        return shared_state, calc, black_level, sample

    def test_radiometer_feeds_tracker_and_uses_its_pedestal(self):
        shared_state, calc, black_level, sample = self._radiometer_harness()
        accumulator = solver.RadiometerAccumulator()
        solver.update_radiometric_sqm(
            shared_state,
            calc,
            accumulator,
            sample,
            now=1001.0,
            black_level_tracker=black_level,
        )
        args, kwargs = black_level.add_sample.call_args
        assert args[0] == 0.5 and args[1] == 250.0
        assert kwargs["stable"] is True
        # Published pedestal is the tracked one (zero-touch path).
        details = shared_state.set_sqm_details.call_args[0][0]
        assert details["pedestal"] == 237.5
        assert details["black_level_tracked"] is True

    def test_radiometer_withholds_tracker_sample_under_cloud(self):
        shared_state, calc, black_level, sample = self._radiometer_harness(cloudy=True)
        accumulator = solver.RadiometerAccumulator()
        solver.update_radiometric_sqm(
            shared_state,
            calc,
            accumulator,
            sample,
            now=1001.0,
            black_level_tracker=black_level,
        )
        assert black_level.add_sample.call_args.kwargs["stable"] is False

    def test_radiometer_ignores_tracker_when_calibrated(self):
        shared_state, calc, black_level, sample = self._radiometer_harness(
            calibrated=True
        )
        accumulator = solver.RadiometerAccumulator()
        solver.update_radiometric_sqm(
            shared_state,
            calc,
            accumulator,
            sample,
            now=1001.0,
            black_level_tracker=black_level,
        )
        # Wizard bias + dark current is authoritative over the tracker.
        details = shared_state.set_sqm_details.call_args[0][0]
        assert details["pedestal"] == calc.profile.bias_offset + (
            calc.profile.dark_current_rate * 0.5
        )
        assert details["black_level_tracked"] is False

    def test_radiometer_duplicate_sequence_not_refed(self):
        shared_state, calc, black_level, sample = self._radiometer_harness()
        accumulator = solver.RadiometerAccumulator()
        solver.update_radiometric_sqm(
            shared_state,
            calc,
            accumulator,
            sample,
            now=1001.0,
            black_level_tracker=black_level,
        )
        solver.update_radiometric_sqm(
            shared_state,
            calc,
            accumulator,
            sample,
            now=1002.5,
            black_level_tracker=black_level,
        )
        # Same camera frame seen twice by the loop: fed exactly once.
        assert black_level.add_sample.call_count == 1
