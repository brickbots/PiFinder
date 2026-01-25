import json

import pytest
import numpy as np

from PiFinder.sqm import SQM
from PiFinder.sqm.noise_floor import NoiseFloorEstimator
from PiFinder.sqm.camera_profiles import (
    CameraProfile,
    get_camera_profile,
    detect_camera_type,
)
from PiFinder.sqm.save_sweep_metadata import save_sweep_metadata


@pytest.mark.unit
class TestSQMExtinction:
    """
    Unit tests for SQM atmospheric extinction correction.
    """

    def test_extinction_at_zenith(self):
        """Test that extinction at zenith is 0.0 mag (ASTAP convention: zenith is reference)"""
        sqm = SQM()
        extinction = sqm._atmospheric_extinction(90.0)
        assert extinction == pytest.approx(0.0, abs=0.0001)

    def test_extinction_at_45_degrees(self):
        """Test extinction at 45° altitude using Pickering airmass"""
        sqm = SQM()
        extinction = sqm._atmospheric_extinction(45.0)
        # Pickering (2002) airmass at 45° ≈ 1.4124
        # ASTAP convention: 0.28 * (airmass - 1)
        pickering_airmass = sqm._pickering_airmass(45.0)
        expected = 0.28 * (pickering_airmass - 1)
        assert extinction == pytest.approx(expected, abs=0.001)

    def test_extinction_at_30_degrees(self):
        """Test extinction at 30° altitude using Pickering airmass"""
        sqm = SQM()
        extinction = sqm._atmospheric_extinction(30.0)
        # Pickering (2002) airmass at 30° ≈ 1.995
        # ASTAP convention: 0.28 * (airmass - 1) ≈ 0.279
        pickering_airmass = sqm._pickering_airmass(30.0)
        expected = 0.28 * (pickering_airmass - 1)
        assert extinction == pytest.approx(expected, abs=0.001)

    def test_extinction_increases_toward_horizon(self):
        """Test that extinction increases as altitude decreases"""
        sqm = SQM()
        altitudes = [90, 60, 45, 30, 20, 10]
        extinctions = [sqm._atmospheric_extinction(alt) for alt in altitudes]

        # Extinction should increase monotonically as altitude decreases
        for i in range(len(extinctions) - 1):
            assert (
                extinctions[i] < extinctions[i + 1]
            ), f"Extinction at {altitudes[i]}° should be less than at {altitudes[i+1]}°"

    def test_extinction_minimum_is_at_zenith(self):
        """Test that zenith (90°) has zero extinction (ASTAP convention)"""
        sqm = SQM()
        zenith_extinction = sqm._atmospheric_extinction(90.0)

        # Zenith should have exactly zero extinction
        assert zenith_extinction == pytest.approx(0.0, abs=0.0001)

        # Test various altitudes - all should have more extinction than zenith
        test_altitudes = [89, 80, 70, 60, 50, 40, 30, 20, 10]
        for alt in test_altitudes:
            extinction = sqm._atmospheric_extinction(alt)
            assert extinction > zenith_extinction, (
                f"Extinction at {alt}° ({extinction:.3f}) should be greater than "
                f"at zenith ({zenith_extinction:.3f})"
            )

    def test_extinction_invalid_altitude(self):
        """Test that invalid altitudes (<=0) return 0.0"""
        sqm = SQM()
        assert sqm._atmospheric_extinction(0.0) == 0.0
        assert sqm._atmospheric_extinction(-10.0) == 0.0
        assert sqm._atmospheric_extinction(-90.0) == 0.0

    def test_extinction_airmass_relationship(self):
        """Test the Pickering airmass formula: extinction = 0.28 * (airmass - 1)"""
        sqm = SQM()

        # At 90°: airmass ≈ 1.0, extinction ≈ 0
        altitude = 90.0
        airmass = sqm._pickering_airmass(altitude)
        extinction = sqm._atmospheric_extinction(altitude)
        assert extinction == pytest.approx(0.28 * (airmass - 1), abs=0.0001)
        assert extinction == pytest.approx(0.0, abs=0.0001)

        # At 30°: Pickering airmass ≈ 1.995
        altitude = 30.0
        airmass = sqm._pickering_airmass(altitude)
        extinction = sqm._atmospheric_extinction(altitude)
        assert extinction == pytest.approx(0.28 * (airmass - 1), abs=0.0001)
        assert airmass == pytest.approx(1.995, abs=0.01)

        # At 6°: Pickering airmass is more accurate near horizon than simple formula
        altitude = 6.0
        airmass = sqm._pickering_airmass(altitude)
        extinction = sqm._atmospheric_extinction(altitude)
        assert extinction == pytest.approx(0.28 * (airmass - 1), abs=0.001)


@pytest.mark.unit
class TestPickeringAirmass:
    """
    Unit tests for Pickering (2002) airmass formula.
    """

    def test_airmass_at_zenith(self):
        """Test airmass at zenith is 1.0"""
        sqm = SQM()
        airmass = sqm._pickering_airmass(90.0)
        assert airmass == pytest.approx(1.0, abs=0.001)

    def test_airmass_at_45_degrees(self):
        """Test airmass at 45° altitude"""
        sqm = SQM()
        airmass = sqm._pickering_airmass(45.0)
        # Pickering airmass at 45° ≈ 1.413 (slightly less than simple 1/sin(45°) = 1.414)
        assert airmass == pytest.approx(1.413, abs=0.01)

    def test_airmass_at_30_degrees(self):
        """Test airmass at 30° altitude"""
        sqm = SQM()
        airmass = sqm._pickering_airmass(30.0)
        # Pickering airmass at 30° ≈ 1.995 (slightly less than simple 1/sin(30°) = 2.0)
        assert airmass == pytest.approx(1.995, abs=0.01)

    def test_airmass_at_10_degrees(self):
        """Test airmass at 10° altitude shows Pickering correction"""
        sqm = SQM()
        pickering = sqm._pickering_airmass(10.0)
        simple = 1.0 / np.sin(np.radians(10.0))
        # Pickering gives ~5.60, simple gives ~5.76 (3% difference)
        assert pickering == pytest.approx(5.60, abs=0.05)
        assert simple > pickering  # Simple overestimates at low altitudes

    def test_airmass_at_5_degrees(self):
        """Test airmass at 5° altitude shows significant Pickering correction."""
        sqm = SQM()
        pickering = sqm._pickering_airmass(5.0)
        simple = 1.0 / np.sin(np.radians(5.0))
        # Pickering gives ~10.3, simple gives ~11.47 (10% difference)
        # Expected range from literature: ≈ 9-10
        assert pickering == pytest.approx(10.3, abs=0.5)
        assert simple == pytest.approx(11.47, abs=0.1)
        assert simple > pickering  # Simple significantly overestimates near horizon

    def test_airmass_increases_toward_horizon(self):
        """Test airmass increases monotonically toward horizon"""
        sqm = SQM()
        altitudes = [90, 60, 45, 30, 20, 10, 5]
        airmasses = [sqm._pickering_airmass(alt) for alt in altitudes]

        for i in range(len(airmasses) - 1):
            assert airmasses[i] < airmasses[i + 1], (
                f"Airmass at {altitudes[i]}° ({airmasses[i]:.3f}) should be less than "
                f"at {altitudes[i+1]}° ({airmasses[i+1]:.3f})"
            )


@pytest.mark.unit
class TestSQMCalculation:
    """
    Unit tests for SQM calculation methods.
    """

    def test_calculate_returns_tuple(self):
        """Test that calculate() returns a tuple (value, details_dict)"""
        np.random.seed(42)
        sqm = SQM()

        # Create minimal mock data
        solution = {
            "FOV": 10.0,
            "matched_centroids": np.array([[100, 100], [200, 200], [300, 300]]),
            "matched_stars": [
                [45.0, 30.0, 5.0],
                [45.1, 30.1, 6.0],
                [45.2, 30.2, 7.0],
            ],
        }

        centroids = [[100, 100], [200, 200], [300, 300]]
        image = np.random.randint(800, 1200, (512, 512), dtype=np.uint16)

        # Add bright spots for stars at (row, col) positions
        for row, col in centroids:
            image[row - 2 : row + 3, col - 2 : col + 3] += 5000

        result = sqm.calculate(
            centroids=centroids,
            solution=solution,
            image=image,
            exposure_sec=0.5,
            altitude_deg=90.0,
        )

        # Should return tuple
        assert isinstance(result, tuple)
        assert len(result) == 2

        # First element should be float or None
        assert isinstance(result[0], (float, type(None)))

        # Second element should be dict
        assert isinstance(result[1], dict)

    def test_calculate_extinction_applied(self):
        """Test that extinction correction follows ASTAP convention"""
        np.random.seed(42)
        sqm = SQM()

        solution = {
            "FOV": 10.0,
            "matched_centroids": np.array([[100, 100], [200, 200], [300, 300]]),
            "matched_stars": [
                [45.0, 30.0, 5.0],
                [45.1, 30.1, 6.0],
                [45.2, 30.2, 7.0],
            ],
        }

        centroids = [[100, 100], [200, 200], [300, 300]]
        image = np.random.randint(800, 1200, (512, 512), dtype=np.uint16)

        for row, col in centroids:
            image[row - 2 : row + 3, col - 2 : col + 3] += 5000

        # Calculate at zenith
        # Note: Use high saturation threshold for uint16 test images
        _sqm_zenith, details_zenith = sqm.calculate(
            centroids=centroids,
            solution=solution,
            image=image,
            exposure_sec=0.5,
            altitude_deg=90.0,
            saturation_threshold=65000,
        )

        # Calculate at 30° (2× airmass)
        _sqm_30deg, details_30deg = sqm.calculate(
            centroids=centroids,
            solution=solution,
            image=image,
            exposure_sec=0.5,
            altitude_deg=30.0,
            saturation_threshold=65000,
        )

        # Check extinction values (ASTAP convention: 0 at zenith)
        # Pickering airmass at 30° ≈ 1.995, so extinction ≈ 0.28 * 0.995 ≈ 0.279
        assert details_zenith["extinction_for_altitude"] == pytest.approx(0.0, abs=0.001)
        expected_ext_30 = 0.28 * (sqm._pickering_airmass(30.0) - 1)
        assert details_30deg["extinction_for_altitude"] == pytest.approx(
            expected_ext_30, abs=0.001
        )

        # Uncorrected SQM should be the same (same image, same stars)
        assert details_zenith["sqm_uncorrected"] == pytest.approx(
            details_30deg["sqm_uncorrected"], abs=0.001
        )

        # sqm_final is raw (no extinction), sqm_altitude_corrected adds extinction
        # At zenith: sqm_final == sqm_altitude_corrected (extinction is 0)
        assert details_zenith["sqm_final"] == pytest.approx(
            details_zenith["sqm_altitude_corrected"], abs=0.001
        )

        # At 30°: sqm_altitude_corrected = sqm_final + extinction
        assert details_30deg["sqm_altitude_corrected"] == pytest.approx(
            details_30deg["sqm_final"] + expected_ext_30, abs=0.001
        )

    def test_calculate_missing_fov(self):
        """Test that calculate() returns None when FOV is missing"""
        np.random.seed(42)
        sqm = SQM()

        solution = {
            "matched_centroids": np.array([[100, 100]]),
            "matched_stars": [[45.0, 30.0, 5.0]],
        }

        image = np.random.randint(800, 1200, (512, 512), dtype=np.uint16)

        sqm_value, details = sqm.calculate(
            centroids=[[100, 100]],
            solution=solution,
            image=image,
            exposure_sec=0.5,
            altitude_deg=90.0,
        )

        assert sqm_value is None
        assert details == {}

    def test_calculate_no_matched_stars(self):
        """Test that calculate() returns None when no stars are matched"""
        np.random.seed(42)
        sqm = SQM()

        solution = {
            "FOV": 10.0,
            "matched_centroids": np.array([]),
            "matched_stars": [],
        }

        image = np.random.randint(800, 1200, (512, 512), dtype=np.uint16)

        sqm_value, details = sqm.calculate(
            centroids=[],
            solution=solution,
            image=image,
            exposure_sec=0.5,
            altitude_deg=90.0,
        )

        assert sqm_value is None
        assert details == {}

    def test_calculate_asymmetric_centroids(self):
        """Test with asymmetric centroids to verify (row, col) convention.

        This test uses centroids where row != col to catch any (x,y)/(y,x) confusion.
        If the coordinate convention is wrong, stars won't be found at the expected
        positions and the calculation will fail or produce incorrect results.
        """
        np.random.seed(42)
        sqm = SQM()

        # CRITICAL: Use asymmetric coordinates to catch any (x,y)/(y,x) confusion
        # Format is (row, col) = (y, x), NOT (x, y)
        asymmetric_centroids = np.array([[50, 400], [100, 300], [150, 200]])

        solution = {
            "FOV": 10.0,
            "matched_centroids": asymmetric_centroids,
            "matched_stars": [
                [45.0, 30.0, 5.0],
                [45.1, 30.1, 6.0],
                [45.2, 30.2, 7.0],
            ],
        }

        image = np.random.randint(800, 1200, (512, 512), dtype=np.uint16)

        # Add bright spots at correct positions: image[row, col]
        for row, col in asymmetric_centroids:
            image[row - 2 : row + 3, col - 2 : col + 3] += 5000

        result, details = sqm.calculate(
            centroids=asymmetric_centroids.tolist(),
            solution=solution,
            image=image,
            exposure_sec=0.5,
            altitude_deg=90.0,
            saturation_threshold=65000,
        )

        # Should find valid SQM (stars are at correct positions)
        assert result is not None, "SQM calculation failed with asymmetric centroids"
        assert details["n_matched_stars"] == 3

        # Verify star fluxes are positive (stars were found at correct positions)
        valid_fluxes = [f for f in details["star_fluxes"] if f > 0]
        assert len(valid_fluxes) == 3, (
            f"Expected 3 valid star fluxes but got {len(valid_fluxes)}. "
            "This may indicate coordinate convention mismatch."
        )


@pytest.mark.unit
class TestSQMFieldParameters:
    """
    Unit tests for SQM field parameter calculations.
    """

    def test_field_parameters_calculation(self):
        """Test that field parameters are calculated correctly"""
        sqm = SQM()

        # Test with known FOV
        fov_deg = 10.0
        sqm._calc_field_parameters(fov_deg)

        # Image is 512x512 pixels
        expected_field_arcsec_sq = (fov_deg * 3600) ** 2
        expected_pixels_total = 512**2
        expected_arcsec_sq_per_pixel = expected_field_arcsec_sq / expected_pixels_total

        assert sqm.fov_degrees == fov_deg
        assert sqm.field_arcsec_squared == pytest.approx(
            expected_field_arcsec_sq, abs=0.1
        )
        assert sqm.pixels_total == expected_pixels_total
        assert sqm.arcsec_squared_per_pixel == pytest.approx(
            expected_arcsec_sq_per_pixel, abs=0.01
        )

    def test_field_parameters_different_fov(self):
        """Test field parameters with different FOV values"""
        sqm = SQM()

        test_fovs = [5.0, 10.0, 15.0, 20.0]

        for fov in test_fovs:
            sqm._calc_field_parameters(fov)
            expected_field_arcsec_sq = (fov * 3600) ** 2
            expected_arcsec_sq_per_pixel = expected_field_arcsec_sq / (512**2)

            assert sqm.fov_degrees == fov, f"Failed for FOV={fov}"
            assert sqm.arcsec_squared_per_pixel == pytest.approx(
                expected_arcsec_sq_per_pixel, abs=0.01
            ), f"Failed for FOV={fov}"


@pytest.mark.unit
class TestMzeroCalculation:
    """Unit tests for photometric zero point calculation."""

    def test_mzero_single_star(self):
        """Test mzero calculation with a single star."""
        sqm = SQM()
        # mzero = mag + 2.5 * log10(flux)
        # For flux=1000, mag=5.0: mzero = 5.0 + 2.5*log10(1000) = 5.0 + 7.5 = 12.5
        fluxes = [1000.0]
        mags = [5.0]

        mzero, mzeros = sqm._calculate_mzero(fluxes, mags)

        expected = 5.0 + 2.5 * np.log10(1000)
        assert mzero == pytest.approx(expected, abs=0.001)
        assert len(mzeros) == 1
        assert mzeros[0] == pytest.approx(expected, abs=0.001)

    def test_mzero_flux_weighted_mean(self):
        """Test that mzero uses flux-weighted mean (brighter stars weighted more)."""
        sqm = SQM()
        # Two stars: one bright (high flux), one dim (low flux)
        # The bright star's mzero should dominate
        fluxes = [10000.0, 100.0]  # 100x difference
        mags = [4.0, 8.0]

        mzero, mzeros = sqm._calculate_mzero(fluxes, mags)

        # Individual mzeros
        mzero_bright = 4.0 + 2.5 * np.log10(10000)  # = 14.0
        mzero_dim = 8.0 + 2.5 * np.log10(100)  # = 13.0

        # Flux-weighted: (14.0*10000 + 13.0*100) / (10000+100) ≈ 13.99
        expected_weighted = (mzero_bright * 10000 + mzero_dim * 100) / (10000 + 100)

        assert mzero == pytest.approx(expected_weighted, abs=0.001)
        assert mzeros[0] == pytest.approx(mzero_bright, abs=0.001)
        assert mzeros[1] == pytest.approx(mzero_dim, abs=0.001)

    def test_mzero_skips_negative_flux(self):
        """Test that stars with negative/zero flux are skipped."""
        sqm = SQM()
        fluxes = [1000.0, -1.0, 500.0]  # Middle star is saturated (flux=-1)
        mags = [5.0, 6.0, 5.5]

        mzero, mzeros = sqm._calculate_mzero(fluxes, mags)

        # Should only use stars 0 and 2
        assert mzero is not None
        assert mzeros[0] is not None
        assert mzeros[1] is None  # Skipped
        assert mzeros[2] is not None

    def test_mzero_all_invalid_returns_none(self):
        """Test that all invalid fluxes returns None."""
        sqm = SQM()
        fluxes = [-1.0, 0.0, -5.0]
        mags = [5.0, 6.0, 7.0]

        mzero, mzeros = sqm._calculate_mzero(fluxes, mags)

        assert mzero is None
        assert all(m is None for m in mzeros)


@pytest.mark.unit
class TestApertureOverlapDetection:
    """Unit tests for aperture overlap detection."""

    def test_no_overlap_far_apart(self):
        """Test that far apart stars have no overlap."""
        sqm = SQM()
        # Two stars 100 pixels apart
        centroids = np.array([[100.0, 100.0], [200.0, 100.0]])
        aperture_radius = 5
        annulus_inner = 6
        annulus_outer = 14

        excluded = sqm._detect_aperture_overlaps(
            centroids, aperture_radius, annulus_inner, annulus_outer
        )

        assert len(excluded) == 0

    def test_critical_overlap_apertures_touch(self):
        """Test CRITICAL overlap when apertures overlap (distance < 2*aperture_radius)."""
        sqm = SQM()
        # Two stars 8 pixels apart, aperture_radius=5, so 2*5=10 > 8
        centroids = np.array([[100.0, 100.0], [108.0, 100.0]])
        aperture_radius = 5
        annulus_inner = 6
        annulus_outer = 14

        excluded = sqm._detect_aperture_overlaps(
            centroids, aperture_radius, annulus_inner, annulus_outer
        )

        # Both stars should be excluded
        assert 0 in excluded
        assert 1 in excluded

    def test_high_overlap_aperture_in_annulus(self):
        """Test HIGH overlap when aperture enters another star's annulus."""
        sqm = SQM()
        # Stars 15 pixels apart: aperture(5) + annulus_outer(14) = 19 > 15
        # This means star 1's aperture is inside star 0's annulus
        centroids = np.array([[100.0, 100.0], [115.0, 100.0]])
        aperture_radius = 5
        annulus_inner = 6
        annulus_outer = 14

        excluded = sqm._detect_aperture_overlaps(
            centroids, aperture_radius, annulus_inner, annulus_outer
        )

        # Both should be excluded due to HIGH overlap
        assert 0 in excluded
        assert 1 in excluded

    def test_no_overlap_at_threshold(self):
        """Test no overlap when exactly at safe distance."""
        sqm = SQM()
        # Stars 20 pixels apart: aperture(5) + annulus_outer(14) = 19 < 20
        centroids = np.array([[100.0, 100.0], [120.0, 100.0]])
        aperture_radius = 5
        annulus_inner = 6
        annulus_outer = 14

        excluded = sqm._detect_aperture_overlaps(
            centroids, aperture_radius, annulus_inner, annulus_outer
        )

        assert len(excluded) == 0


@pytest.mark.unit
class TestNoiseFloorEstimation:
    """Unit tests for adaptive noise floor estimation."""

    def test_temporal_noise_calculation(self):
        """Test temporal noise = read_noise + dark_current * exposure."""
        estimator = NoiseFloorEstimator(camera_type="imx296_processed")
        # imx296_processed has read_noise=1.5, dark_current=0.0

        noise = estimator._estimate_temporal_noise(exposure_sec=1.0)

        # With dark_current=0, temporal_noise = read_noise = 1.5
        assert noise == pytest.approx(1.5, abs=0.01)

    def test_noise_floor_uses_theory_when_dark_pixels_below_bias(self):
        """Test that theory is used when dark pixels are impossibly low."""
        estimator = NoiseFloorEstimator(camera_type="imx296_processed")
        # bias_offset for imx296_processed is 6.0

        # Create image with all pixels below bias offset (impossible in reality)
        image = np.full((100, 100), 3.0, dtype=np.float32)

        noise_floor, _ = estimator.estimate_noise_floor(image, exposure_sec=0.5)

        # Should use theoretical floor since dark pixels (3.0) < bias (6.0)
        assert noise_floor >= estimator.profile.bias_offset

    def test_noise_floor_uses_measured_when_valid(self):
        """Test that measured dark pixels are used when valid."""
        np.random.seed(42)
        estimator = NoiseFloorEstimator(camera_type="imx296_processed")
        # bias_offset=6.0, read_noise=1.5, dark_current=0.0
        # theoretical_floor = 6.0 + 1.5 = 7.5

        # Create image with 5th percentile around 8.0 (valid, above bias)
        # Most pixels higher, some low pixels around 8
        image = np.random.uniform(10, 50, (100, 100)).astype(np.float32)
        image[0:5, 0:5] = 8.0  # Dark corner

        noise_floor, _ = estimator.estimate_noise_floor(image, exposure_sec=0.5)

        # Should use min(measured, theoretical)
        # 5th percentile should be around 8, theoretical is 7.5
        # So should use theoretical 7.5
        assert noise_floor == pytest.approx(7.5, abs=0.5)

    def test_noise_floor_clamped_to_bias_offset(self):
        """Test that noise floor is never below bias offset."""
        estimator = NoiseFloorEstimator(camera_type="imx296_processed")

        # Even with weird inputs, should never go below bias
        image = np.full((100, 100), 100.0, dtype=np.float32)

        noise_floor, _ = estimator.estimate_noise_floor(image, exposure_sec=0.5)

        assert noise_floor >= estimator.profile.bias_offset

    def test_history_smoothing_after_multiple_estimates(self):
        """Test that history smoothing kicks in after 5+ estimates."""
        estimator = NoiseFloorEstimator(camera_type="imx296_processed")

        # First 4 estimates - no smoothing yet
        for i in range(4):
            image = np.full((100, 100), 10.0 + i, dtype=np.float32)
            _, details = estimator.estimate_noise_floor(image, exposure_sec=0.5)
            assert details["n_history_samples"] == i + 1

        # 5th estimate - smoothing should kick in
        image = np.full((100, 100), 15.0, dtype=np.float32)
        _, details = estimator.estimate_noise_floor(image, exposure_sec=0.5)
        assert details["n_history_samples"] == 5
        # dark_pixel_smoothed should be median of history, not raw value
        # History: [10, 11, 12, 13, 15] -> median = 12
        assert details["dark_pixel_smoothed"] == pytest.approx(12.0, abs=0.1)

    def test_update_with_zero_sec_sample(self):
        """Test zero-second sample updates profile gradually."""
        np.random.seed(42)
        estimator = NoiseFloorEstimator(camera_type="imx296_processed")
        original_bias = estimator.profile.bias_offset

        # Need 3 samples before profile updates
        for i in range(3):
            # Zero-sec image with bias around 10
            zero_sec = np.random.normal(10.0, 1.5, (100, 100)).astype(np.float32)
            estimator.update_with_zero_sec_sample(zero_sec)

        # After 3 samples, profile should update with EMA (alpha=0.2)
        # new_bias = 0.2 * measured + 0.8 * original
        expected_bias = 0.2 * 10.0 + 0.8 * original_bias
        assert estimator.profile.bias_offset == pytest.approx(expected_bias, abs=0.5)

    def test_validate_estimate_too_close_to_median(self):
        """Test validation fails when noise floor is too close to image median."""
        estimator = NoiseFloorEstimator(camera_type="imx296_processed")

        # Image where darkest pixels are close to median (uniform image)
        # This simulates a situation with no stars/sky gradient
        image = np.full((100, 100), 10.0, dtype=np.float32)

        estimator.estimate_noise_floor(image, exposure_sec=0.5)

        # Should be invalid because noise floor (theoretical ~7.5) is close to median (10)
        # Actually 7.5 is not > 10 * 0.8 = 8, so let's use a different test
        # Need noise floor > median * 0.8 to trigger this
        # Create image where dark pixels are above theoretical floor
        image2 = np.full((100, 100), 8.0, dtype=np.float32)
        estimator2 = NoiseFloorEstimator(camera_type="imx296_processed")

        _, details2 = estimator2.estimate_noise_floor(image2, exposure_sec=0.5)

        # noise_floor will be min(8.0, 7.5) = 7.5
        # median = 8.0, threshold = 8.0 * 0.8 = 6.4
        # 7.5 > 6.4, so should be invalid
        assert details2["is_valid"] is False
        assert "median" in details2["validation_reason"].lower()

    def test_get_statistics(self):
        """Test get_statistics returns expected data."""
        np.random.seed(42)
        estimator = NoiseFloorEstimator(camera_type="imx296_processed")

        # Do a few estimates
        for _ in range(3):
            image = np.random.uniform(10, 50, (100, 100)).astype(np.float32)
            estimator.estimate_noise_floor(image, exposure_sec=0.5)

        stats = estimator.get_statistics()

        assert stats["camera_type"] == "imx296_processed"
        assert stats["n_estimates"] == 3
        assert stats["n_history_samples"] == 3
        assert "dark_pixel_mean" in stats
        assert "dark_pixel_std" in stats
        assert "dark_pixel_median" in stats

    def test_reset_clears_state(self):
        """Test reset clears all history and statistics."""
        np.random.seed(42)
        estimator = NoiseFloorEstimator(camera_type="imx296_processed")

        # Build up some state
        for _ in range(5):
            image = np.random.uniform(10, 50, (100, 100)).astype(np.float32)
            estimator.estimate_noise_floor(image, exposure_sec=0.5)

        assert estimator.n_estimates == 5
        assert len(estimator.dark_pixel_history) == 5

        # Reset
        estimator.reset()

        assert estimator.n_estimates == 0
        assert len(estimator.dark_pixel_history) == 0
        assert len(estimator.zero_sec_history) == 0

    def test_save_and_load_calibration(self, tmp_path, monkeypatch):
        """Test calibration save/load round-trip."""
        # Redirect Path.home() to tmp_path
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        # Create PiFinder_data directory
        (tmp_path / "PiFinder_data").mkdir()

        estimator = NoiseFloorEstimator(camera_type="imx296_processed")

        # Save calibration with new values
        result = estimator.save_calibration(
            bias_offset=25.0, read_noise=3.5, dark_current_rate=0.5
        )
        assert result is True

        # Verify profile was updated
        assert estimator.profile.bias_offset == 25.0
        assert estimator.profile.read_noise_adu == 3.5
        assert estimator.profile.dark_current_rate == 0.5

        # Create new estimator - should load the saved calibration
        estimator2 = NoiseFloorEstimator(camera_type="imx296_processed")

        # Should have loaded the saved values (not the defaults)
        assert estimator2.profile.bias_offset == 25.0
        assert estimator2.profile.read_noise_adu == 3.5
        assert estimator2.profile.dark_current_rate == 0.5


@pytest.mark.unit
class TestMeasureStarFluxWithLocalBackground:
    """Unit tests for SQM._measure_star_flux_with_local_background()."""

    def test_single_star_flux_measurement(self):
        """Test flux measurement for a single star with known values."""
        np.random.seed(42)
        sqm = SQM()

        # Create image with uniform background of 100 ADU
        image = np.full((100, 100), 100.0, dtype=np.float32)

        # Add a star at center (50, 50) with 1000 ADU above background
        # Star in 5-pixel radius aperture
        y, x = np.ogrid[:100, :100]
        dist_sq = (x - 50) ** 2 + (y - 50) ** 2
        star_mask = dist_sq <= 25  # radius 5
        image[star_mask] += 1000

        centroids = np.array([[50, 50]])  # (row, col) format

        fluxes, backgrounds, n_saturated = sqm._measure_star_flux_with_local_background(
            image=image,
            centroids=centroids,
            aperture_radius=5,
            annulus_inner_radius=6,
            annulus_outer_radius=14,
            saturation_threshold=65000,
        )

        # Background should be ~100 (the uniform background)
        assert backgrounds[0] == pytest.approx(100.0, abs=1.0)

        # Flux should be ~1000 * number_of_aperture_pixels
        # Aperture area for r=5 is approximately pi*5^2 = 78.5 pixels
        assert fluxes[0] > 50000  # Should have significant positive flux
        assert n_saturated == 0

    def test_saturated_star_detection(self):
        """Test that saturated stars are detected and marked with flux=-1."""
        sqm = SQM()

        # Create image with background
        image = np.full((100, 100), 50.0, dtype=np.float32)

        # Add a saturated star (pixel value >= threshold)
        image[48:53, 48:53] = 255  # Saturated pixels

        centroids = np.array([[50, 50]])

        fluxes, backgrounds, n_saturated = sqm._measure_star_flux_with_local_background(
            image=image,
            centroids=centroids,
            aperture_radius=5,
            annulus_inner_radius=6,
            annulus_outer_radius=14,
            saturation_threshold=250,
        )

        assert fluxes[0] == -1  # Saturated stars get flux=-1
        assert n_saturated == 1

    def test_multiple_stars(self):
        """Test flux measurement for multiple stars."""
        np.random.seed(42)
        sqm = SQM()

        # Create image with uniform background
        image = np.full((200, 200), 80.0, dtype=np.float32)

        # Add two stars at different positions
        y, x = np.ogrid[:200, :200]

        # Star 1 at (50, 50)
        dist_sq1 = (x - 50) ** 2 + (y - 50) ** 2
        image[dist_sq1 <= 16] += 500  # radius 4

        # Star 2 at (150, 150)
        dist_sq2 = (x - 150) ** 2 + (y - 150) ** 2
        image[dist_sq2 <= 16] += 800  # brighter star

        centroids = np.array([[50, 50], [150, 150]])

        fluxes, backgrounds, n_saturated = sqm._measure_star_flux_with_local_background(
            image=image,
            centroids=centroids,
            aperture_radius=5,
            annulus_inner_radius=6,
            annulus_outer_radius=14,
            saturation_threshold=65000,
        )

        assert len(fluxes) == 2
        assert len(backgrounds) == 2
        assert fluxes[0] > 0  # Both should have positive flux
        assert fluxes[1] > 0
        assert fluxes[1] > fluxes[0]  # Star 2 should be brighter
        assert n_saturated == 0

    def test_star_near_edge(self):
        """Test flux measurement for a star near image edge."""
        sqm = SQM()

        # Create small image
        image = np.full((50, 50), 60.0, dtype=np.float32)

        # Add star near edge
        image[5:10, 5:10] += 300

        centroids = np.array([[7, 7]])

        fluxes, backgrounds, n_saturated = sqm._measure_star_flux_with_local_background(
            image=image,
            centroids=centroids,
            aperture_radius=3,
            annulus_inner_radius=4,
            annulus_outer_radius=8,
            saturation_threshold=65000,
        )

        # Should still return a result (clipped to image bounds)
        assert len(fluxes) == 1
        assert fluxes[0] > 0

    def test_local_background_varies_per_star(self):
        """Test that each star uses its own local background."""
        sqm = SQM()

        # Create image with gradient background
        image = np.zeros((200, 200), dtype=np.float32)
        for i in range(200):
            image[i, :] = 50 + i * 0.5  # Gradient from 50 to 150

        # Add stars in different background regions
        y, x = np.ogrid[:200, :200]

        # Star 1 in low background region (row 30)
        dist_sq1 = (x - 100) ** 2 + (y - 30) ** 2
        image[dist_sq1 <= 16] += 500

        # Star 2 in high background region (row 170)
        dist_sq2 = (x - 100) ** 2 + (y - 170) ** 2
        image[dist_sq2 <= 16] += 500

        centroids = np.array([[30, 100], [170, 100]])

        fluxes, backgrounds, n_saturated = sqm._measure_star_flux_with_local_background(
            image=image,
            centroids=centroids,
            aperture_radius=5,
            annulus_inner_radius=6,
            annulus_outer_radius=14,
            saturation_threshold=65000,
        )

        # Backgrounds should be different (local to each star)
        assert backgrounds[0] < backgrounds[1]
        # Background at row 30 should be ~65, at row 170 should be ~135
        assert backgrounds[0] == pytest.approx(65, abs=10)
        assert backgrounds[1] == pytest.approx(135, abs=10)


@pytest.mark.unit
class TestGetCameraProfile:
    """Unit tests for camera_profiles.get_camera_profile()."""

    def test_get_known_camera_profile(self):
        """Test getting profiles for known camera types."""
        profile = get_camera_profile("imx296")

        assert isinstance(profile, CameraProfile)
        assert profile.format == "R10"
        assert profile.bit_depth == 10
        assert profile.analog_gain == 15.0

    def test_get_processed_camera_profile(self):
        """Test getting processed (8-bit) camera profiles."""
        profile = get_camera_profile("imx296_processed")

        assert isinstance(profile, CameraProfile)
        assert profile.bit_depth == 8
        assert profile.format == "L"

    def test_get_all_known_profiles(self):
        """Test that all documented camera types are accessible."""
        camera_types = [
            "imx296",
            "imx462",
            "imx290",
            "hq",
            "imx296_processed",
            "imx462_processed",
            "imx290_processed",
            "hq_processed",
        ]

        for camera_type in camera_types:
            profile = get_camera_profile(camera_type)
            assert isinstance(profile, CameraProfile)
            assert profile.raw_size is not None

    def test_unknown_camera_raises_error(self):
        """Test that unknown camera type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_camera_profile("unknown_camera")

        assert "unknown_camera" in str(exc_info.value).lower()
        assert "available" in str(exc_info.value).lower()


@pytest.mark.unit
class TestDetectCameraType:
    """Unit tests for camera_profiles.detect_camera_type()."""

    def test_detect_imx296(self):
        """Test detection of IMX296 sensor."""
        assert detect_camera_type("imx296") == "imx296"
        assert detect_camera_type("IMX296") == "imx296"
        assert detect_camera_type("imx296_mono") == "imx296"

    def test_detect_imx290_maps_to_imx462(self):
        """Test that IMX290 maps to IMX462 profile (driver compatibility)."""
        assert detect_camera_type("imx290") == "imx462"
        assert detect_camera_type("IMX290") == "imx462"

    def test_detect_imx477_maps_to_hq(self):
        """Test that IMX477 maps to HQ profile."""
        assert detect_camera_type("imx477") == "hq"
        assert detect_camera_type("IMX477") == "hq"
        assert detect_camera_type("raspberry_pi_imx477") == "hq"

    def test_unknown_hardware_raises_error(self):
        """Test that unknown hardware ID raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            detect_camera_type("unknown_sensor")

        assert "unknown_sensor" in str(exc_info.value).lower()
        assert "supported" in str(exc_info.value).lower()


@pytest.mark.unit
class TestCropAndRotate:
    """Unit tests for CameraProfile.crop_and_rotate()."""

    def test_no_crop_no_rotation(self):
        """Test with no cropping and no rotation."""
        profile = CameraProfile(
            format="R10",
            raw_size=(100, 100),
            analog_gain=1.0,
            crop_y=(0, 0),
            crop_x=(0, 0),
            rotation_90=0,
        )

        arr = np.arange(100 * 100).reshape(100, 100)
        result = profile.crop_and_rotate(arr)

        assert result.shape == (100, 100)
        np.testing.assert_array_equal(result, arr)

    def test_vertical_crop(self):
        """Test vertical (y) cropping."""
        profile = CameraProfile(
            format="R10",
            raw_size=(100, 100),
            analog_gain=1.0,
            crop_y=(10, 20),  # Remove 10 from top, 20 from bottom
            crop_x=(0, 0),
            rotation_90=0,
        )

        arr = np.arange(100 * 100).reshape(100, 100)
        result = profile.crop_and_rotate(arr)

        assert result.shape == (70, 100)  # 100 - 10 - 20 = 70
        np.testing.assert_array_equal(result, arr[10:-20, :])

    def test_horizontal_crop(self):
        """Test horizontal (x) cropping."""
        profile = CameraProfile(
            format="R10",
            raw_size=(100, 100),
            analog_gain=1.0,
            crop_y=(0, 0),
            crop_x=(15, 25),  # Remove 15 from left, 25 from right
            rotation_90=0,
        )

        arr = np.arange(100 * 100).reshape(100, 100)
        result = profile.crop_and_rotate(arr)

        assert result.shape == (100, 60)  # 100 - 15 - 25 = 60
        np.testing.assert_array_equal(result, arr[:, 15:-25])

    def test_both_crops(self):
        """Test both vertical and horizontal cropping."""
        profile = CameraProfile(
            format="R10",
            raw_size=(100, 100),
            analog_gain=1.0,
            crop_y=(5, 10),
            crop_x=(10, 15),
            rotation_90=0,
        )

        arr = np.arange(100 * 100).reshape(100, 100)
        result = profile.crop_and_rotate(arr)

        assert result.shape == (85, 75)  # (100-5-10, 100-10-15)
        np.testing.assert_array_equal(result, arr[5:-10, 10:-15])

    def test_rotation_90(self):
        """Test 90-degree counter-clockwise rotation."""
        profile = CameraProfile(
            format="R10",
            raw_size=(100, 50),
            analog_gain=1.0,
            crop_y=(0, 0),
            crop_x=(0, 0),
            rotation_90=1,  # 90° CCW
        )

        arr = np.arange(100 * 50).reshape(100, 50)
        result = profile.crop_and_rotate(arr)

        assert result.shape == (50, 100)  # Dimensions swapped
        np.testing.assert_array_equal(result, np.rot90(arr, 1))

    def test_rotation_180(self):
        """Test 180-degree rotation."""
        profile = CameraProfile(
            format="R10",
            raw_size=(100, 100),
            analog_gain=1.0,
            crop_y=(0, 0),
            crop_x=(0, 0),
            rotation_90=2,  # 180°
        )

        arr = np.arange(100 * 100).reshape(100, 100)
        result = profile.crop_and_rotate(arr)

        assert result.shape == (100, 100)
        np.testing.assert_array_equal(result, np.rot90(arr, 2))

    def test_crop_then_rotate(self):
        """Test that crop is applied before rotation."""
        profile = CameraProfile(
            format="R10",
            raw_size=(100, 80),
            analog_gain=1.0,
            crop_y=(10, 10),  # 100 -> 80
            crop_x=(0, 0),
            rotation_90=1,  # 90° CCW
        )

        arr = np.arange(100 * 80).reshape(100, 80)
        result = profile.crop_and_rotate(arr)

        # After crop: (80, 80), after 90° rotation: (80, 80)
        assert result.shape == (80, 80)

        # Verify correct order: crop first, then rotate
        expected = np.rot90(arr[10:-10, :], 1)
        np.testing.assert_array_equal(result, expected)

    def test_imx296_profile_crop_and_rotate(self):
        """Test with actual IMX296 profile settings."""
        profile = get_camera_profile("imx296")

        # Create array matching IMX296 raw size
        arr = np.ones(profile.raw_size[::-1], dtype=np.uint16)  # (height, width)

        result = profile.crop_and_rotate(arr)

        # IMX296 crops 184 from each side horizontally and rotates 180°
        # Original: (1088, 1456) -> crop to (1088, 1088) -> same after 180° rotation
        expected_width = profile.raw_size[0] - profile.crop_x[0] - profile.crop_x[1]
        expected_height = profile.raw_size[1] - profile.crop_y[0] - profile.crop_y[1]

        # After rotation, if 180°, dimensions stay same
        assert result.shape == (expected_height, expected_width)


@pytest.mark.unit
class TestSaveSweepMetadata:
    """Unit tests for save_sweep_metadata.save_sweep_metadata()."""

    def test_save_minimal_metadata(self, tmp_path):
        """Test saving metadata with only required fields."""
        sweep_dir = tmp_path / "sweep_test"
        sweep_dir.mkdir()

        result = save_sweep_metadata(
            sweep_dir=sweep_dir,
            observer_lat=50.85,
            observer_lon=4.35,
        )

        assert result == sweep_dir / "sweep_metadata.json"
        assert result.exists()

        with open(result) as f:
            data = json.load(f)

        assert data["observer"]["latitude_deg"] == 50.85
        assert data["observer"]["longitude_deg"] == 4.35
        assert "timestamp" in data
        assert data["sweep_directory"] == str(sweep_dir)

    def test_save_full_metadata(self, tmp_path):
        """Test saving metadata with all optional fields."""
        sweep_dir = tmp_path / "sweep_full"
        sweep_dir.mkdir()

        result = save_sweep_metadata(
            sweep_dir=sweep_dir,
            observer_lat=50.85,
            observer_lon=4.35,
            observer_altitude_m=100.0,
            gps_datetime="2024-01-15T22:30:00+00:00",
            reference_sqm=21.5,
            ra_deg=180.0,
            dec_deg=45.0,
            altitude_deg=60.0,
            azimuth_deg=90.0,
            notes="Clear sky, no moon",
        )

        with open(result) as f:
            data = json.load(f)

        assert data["observer"]["altitude_m"] == 100.0
        assert data["timestamp"] == "2024-01-15T22:30:00+00:00"
        assert data["reference_sqm"] == 21.5
        assert data["coordinates"]["ra_deg"] == 180.0
        assert data["coordinates"]["dec_deg"] == 45.0
        assert data["coordinates"]["altitude_deg"] == 60.0
        assert data["coordinates"]["azimuth_deg"] == 90.0
        assert data["notes"] == "Clear sky, no moon"

    def test_save_partial_coordinates(self, tmp_path):
        """Test saving metadata with only RA/Dec (no alt/az)."""
        sweep_dir = tmp_path / "sweep_partial"
        sweep_dir.mkdir()

        save_sweep_metadata(
            sweep_dir=sweep_dir,
            observer_lat=50.85,
            observer_lon=4.35,
            ra_deg=120.0,
            dec_deg=30.0,
        )

        with open(sweep_dir / "sweep_metadata.json") as f:
            data = json.load(f)

        assert data["coordinates"]["ra_deg"] == 120.0
        assert data["coordinates"]["dec_deg"] == 30.0
        assert "altitude_deg" not in data["coordinates"]
        assert "azimuth_deg" not in data["coordinates"]

    def test_coordinates_require_both_ra_dec(self, tmp_path):
        """Test that coordinates block requires both RA and Dec."""
        sweep_dir = tmp_path / "sweep_ra_only"
        sweep_dir.mkdir()

        # Only RA, no Dec - should not create coordinates block
        save_sweep_metadata(
            sweep_dir=sweep_dir,
            observer_lat=50.85,
            observer_lon=4.35,
            ra_deg=120.0,  # Only RA, no Dec
        )

        with open(sweep_dir / "sweep_metadata.json") as f:
            data = json.load(f)

        assert "coordinates" not in data

    def test_uses_gps_datetime_when_provided(self, tmp_path):
        """Test that provided GPS datetime is used instead of current time."""
        sweep_dir = tmp_path / "sweep_gps"
        sweep_dir.mkdir()

        gps_time = "2024-06-15T12:00:00+00:00"
        save_sweep_metadata(
            sweep_dir=sweep_dir,
            observer_lat=50.85,
            observer_lon=4.35,
            gps_datetime=gps_time,
        )

        with open(sweep_dir / "sweep_metadata.json") as f:
            data = json.load(f)

        assert data["timestamp"] == gps_time

    def test_nonexistent_directory_raises_error(self, tmp_path):
        """Test that saving to nonexistent directory raises an error."""
        nonexistent = tmp_path / "does_not_exist"

        with pytest.raises(Exception):  # FileNotFoundError or similar
            save_sweep_metadata(
                sweep_dir=nonexistent,
                observer_lat=50.85,
                observer_lon=4.35,
            )
