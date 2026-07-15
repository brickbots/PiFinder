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
class TestApplySqmAnchor:
    def test_zero_delta_is_recorded_but_not_applied(self):
        details = {"sqm_altitude_corrected": 18.5}
        v, d = solver._apply_sqm_anchor(18.3, details, 0.0)
        assert v == 18.3
        assert d["sqm_altitude_corrected"] == 18.5
        assert d["sqm_anchor_delta"] == 0.0

    def test_delta_shifts_value_and_altitude_corrected(self):
        details = {"sqm_altitude_corrected": 18.5}
        v, d = solver._apply_sqm_anchor(18.3, details, 0.25)
        assert v == pytest.approx(18.55)
        assert d["sqm_altitude_corrected"] == pytest.approx(18.75)
        assert d["sqm_anchor_delta"] == 0.25

    def test_none_value_survives(self):
        v, d = solver._apply_sqm_anchor(None, {}, 0.25)
        assert v is None
        assert d["sqm_anchor_delta"] == 0.25

    def test_negative_delta(self):
        v, _d = solver._apply_sqm_anchor(18.3, {}, -0.4)
        assert v == pytest.approx(17.9)
