"""Unit tests for PiFinder.focus -- the self-contained focus HFD detector.

See docs/adr/0005-focus-hfd-self-contained-in-ui.md for the design rationale.
"""

import numpy as np
import pytest

from PiFinder import focus


def _gaussian_frame(
    sigma,
    *,
    size=512,
    amplitude=200.0,
    background=20.0,
    center=(256, 256),
    noise=1.0,
    seed=42,
):
    """Render a single 2D-Gaussian star on a (optionally noisy) background."""
    rng = np.random.default_rng(seed)
    if noise > 0:
        img = rng.normal(background, noise, (size, size)).astype(np.float32)
    else:
        img = np.full((size, size), background, dtype=np.float32)
    cy, cx = center
    y, x = np.ogrid[:size, :size]
    img += amplitude * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma**2))
    return np.clip(img, 0, 255)


@pytest.mark.unit
class TestHalfFluxDiameter:
    def test_gaussian_hfd_matches_theory(self):
        """For a 2D Gaussian, HFD = 2 * E[r] = 2 * sigma * sqrt(pi/2) ~ 2.5066 sigma."""
        sigma = 4.0
        img = _gaussian_frame(sigma, amplitude=200.0, background=0.0, noise=0.0)
        hfd = focus.half_flux_diameter(img, (256, 256), 0.0, aperture_radius=40)
        expected = 2.0 * sigma * np.sqrt(np.pi / 2.0)
        assert hfd == pytest.approx(expected, rel=0.12)

    def test_monotonic_in_width(self):
        """Wider blob -> larger HFD."""
        hfds = []
        for sigma in (2.0, 4.0, 8.0):
            img = _gaussian_frame(sigma, amplitude=200.0, background=0.0, noise=0.0)
            hfds.append(
                focus.half_flux_diameter(img, (256, 256), 0.0, aperture_radius=45)
            )
        assert hfds[0] < hfds[1] < hfds[2]

    def test_saturated_core_is_finite(self):
        """A saturated (clipped) core must still yield a finite, stable HFD."""
        img = _gaussian_frame(
            5.0, amplitude=1000.0, background=10.0, noise=0.0
        )  # clips at 255
        assert np.max(img) == pytest.approx(255.0)
        hfd = focus.half_flux_diameter(img, (256, 256), 10.0, aperture_radius=40)
        assert np.isfinite(hfd)
        assert hfd > 0.0

    def test_gaussian_fwhm_matches_theory(self):
        sigma = 4.0
        img = _gaussian_frame(sigma, amplitude=200.0, background=10.0, noise=0.0)
        blob = focus.detect_stars(img, n=1)[0]
        fwhm = focus.full_width_half_maximum(img, blob)
        expected = 2.0 * np.sqrt(2.0 * np.log(2.0)) * sigma
        assert fwhm == pytest.approx(expected, rel=0.15)

    def test_no_flux_returns_zero(self):
        img = np.full((128, 128), 30.0, dtype=np.float32)
        hfd = focus.half_flux_diameter(img, (64, 64), 30.0, aperture_radius=20)
        assert hfd == 0.0


@pytest.mark.unit
class TestDetectStars:
    def test_finds_a_clear_star(self):
        img = _gaussian_frame(4.0, amplitude=180.0, background=20.0)
        blobs = focus.detect_stars(img)
        assert len(blobs) >= 1
        brightest = blobs[0]
        assert brightest.y == pytest.approx(256, abs=3)
        assert brightest.x == pytest.approx(256, abs=3)

    def test_rejects_hot_pixel(self):
        img = np.full((128, 128), 20.0, dtype=np.float32)
        img[64, 64] = 255.0  # single-pixel spike
        blobs = focus.detect_stars(img)
        assert blobs == []

    def test_returns_at_most_n(self):
        img = np.random.default_rng(1).normal(20.0, 1.0, (512, 512)).astype(np.float32)
        y, x = np.ogrid[:512, :512]
        for i, (cy, cx) in enumerate(
            [(100, 100), (100, 400), (400, 100), (400, 400), (256, 256), (256, 100)]
        ):
            img += (150 + 10 * i) * np.exp(
                -((x - cx) ** 2 + (y - cy) ** 2) / (2 * 3.0**2)
            )
        img = np.clip(img, 0, 255)
        blobs = focus.detect_stars(img, n=3)
        assert len(blobs) == 3

    def test_centroid_is_flux_weighted_not_bounding_box_center(self):
        img = np.zeros((128, 128), dtype=np.float32)
        img[63:66, 62:65] = 40.0
        img[63:66, 65] = 220.0

        blob = focus.detect_stars(img, sigma_k=3.0, n=1)[0]

        # The connected component spans x=62..65, whose box center is 63.5.
        # The brighter right edge must pull the measured stellar centroid right.
        assert blob.x > 64.0
        assert blob.y == pytest.approx(64.0, abs=0.1)


@pytest.mark.unit
class TestTrackBlobs:
    @staticmethod
    def _blob(x, y, peak):
        return focus.Blob(
            x=x,
            y=y,
            peak=peak,
            background=10.0,
            extent=8,
            size_px=20,
        )

    def test_shared_translation_preserves_slots_when_brightness_order_changes(self):
        previous = (
            self._blob(80, 90, 240),
            self._blob(400, 100, 230),
            self._blob(100, 390, 220),
            self._blob(410, 400, 210),
        )
        shift_x, shift_y = 47, -31
        translated = [
            self._blob(blob.x + shift_x, blob.y + shift_y, 100 + index * 30)
            for index, blob in enumerate(previous)
        ]
        distractor = self._blob(250, 250, 255)
        candidates = tuple(
            sorted((*translated, distractor), key=lambda blob: blob.peak, reverse=True)
        )

        tracked = focus.track_blobs(previous, candidates)

        assert [(blob.x, blob.y) for blob in tracked] == [
            (blob.x + shift_x, blob.y + shift_y) for blob in previous
        ]

    def test_missing_star_is_replaced_without_reordering_survivors(self):
        previous = (
            self._blob(80, 90, 240),
            self._blob(400, 100, 230),
            self._blob(100, 390, 220),
            self._blob(410, 400, 210),
        )
        replacement = self._blob(250, 250, 205)
        candidates = (
            self._blob(110, 70, 180),
            self._blob(430, 80, 250),
            self._blob(440, 380, 190),
            replacement,
        )

        tracked = focus.track_blobs(previous, candidates)

        assert (tracked[0].x, tracked[0].y) == (110, 70)
        assert (tracked[1].x, tracked[1].y) == (430, 80)
        assert tracked[2] is replacement
        assert (tracked[3].x, tracked[3].y) == (440, 380)

    def test_slot_tracking_distinguishes_survivors_from_replacements(self):
        previous = (
            self._blob(80, 90, 240),
            self._blob(400, 100, 230),
            self._blob(100, 390, 220),
            self._blob(410, 400, 210),
        )
        replacement = self._blob(250, 250, 205)
        tracked = focus.track_blob_slots(
            previous,
            (
                self._blob(110, 70, 180),
                self._blob(430, 80, 250),
                self._blob(440, 380, 190),
                replacement,
            ),
        )

        assert [previous_index for _blob, previous_index in tracked] == [
            0,
            1,
            None,
            3,
        ]

    def test_catalog_ids_match_focus_centroids_one_to_one(self):
        blobs = (
            self._blob(100.5, 80.5, 240),
            self._blob(399.0, 301.0, 230),
            self._blob(250.0, 250.0, 220),
        )
        # Solver centroids use (y, x), while focus blobs expose x/y fields.
        identities = focus.match_catalog_ids(
            blobs,
            [(300.0, 400.0), (80.0, 100.0), (20.0, 20.0)],
            [71683, 32349, 99999],
        )

        assert identities == (32349, 71683, None)


@pytest.mark.unit
class TestFocusHfd:
    def test_blank_frame_returns_none(self):
        img = np.random.default_rng(7).normal(20.0, 1.0, (512, 512)).astype(np.float32)
        result = focus.focus_hfd(img)
        assert result.median_hfd is None
        assert result.n_used == 0
        assert result.too_defocused is False

    def test_oversized_blob_is_too_defocused(self):
        """A blob broader than the size cap is not measured -> too_defocused."""
        img = _gaussian_frame(40.0, amplitude=200.0, background=20.0)
        result = focus.focus_hfd(img, max_blob_px=50)
        assert result.median_hfd is None
        assert result.n_used == 0
        assert result.too_defocused is True
        assert len(result.blobs) == 1
        assert result.blobs[0].extent > 50

    def test_measures_clear_star(self):
        img = _gaussian_frame(4.0, amplitude=200.0, background=20.0)
        result = focus.focus_hfd(img)
        assert result.median_hfd is not None
        assert result.median_fwhm is not None
        assert result.n_used >= 1
        assert result.too_defocused is False
        expected = 2.0 * 4.0 * np.sqrt(np.pi / 2.0)
        assert result.median_hfd == pytest.approx(expected, rel=0.25)

    def test_median_robust_to_outlier(self):
        """One fat star among several tight ones should not skew the median."""
        rng = np.random.default_rng(3)
        img = rng.normal(20.0, 1.0, (512, 512)).astype(np.float32)
        y, x = np.ogrid[:512, :512]
        tight = [(100, 100), (100, 400), (400, 100), (400, 400)]
        for cy, cx in tight:
            img += 180 * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * 3.0**2))
        # one broad-but-still-measurable outlier
        img += 200 * np.exp(-((x - 256) ** 2 + (y - 256) ** 2) / (2 * 12.0**2))
        img = np.clip(img, 0, 255)
        result = focus.focus_hfd(img, n=5)
        tight_hfd = 2.0 * 3.0 * np.sqrt(np.pi / 2.0)
        assert result.median_hfd == pytest.approx(tight_hfd, rel=0.4)

    def test_display_blobs_are_brightest_first(self):
        rng = np.random.default_rng(9)
        img = rng.normal(20.0, 1.0, (512, 512)).astype(np.float32)
        y, x = np.ogrid[:512, :512]
        for amplitude, (cy, cx) in zip(
            (80.0, 180.0, 120.0, 220.0),
            ((100, 100), (100, 400), (400, 100), (400, 400)),
        ):
            img += amplitude * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * 4.0**2))
        result = focus.focus_hfd(np.clip(img, 0, 255))
        peaks = [blob.peak for blob in result.blobs]
        assert len(peaks) == 4
        assert peaks == sorted(peaks, reverse=True)
