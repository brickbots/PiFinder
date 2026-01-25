import pytest
import numpy as np

from PiFinder.sqm import SQM


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

        # Add bright spots for stars
        for x, y in centroids:
            image[y - 2 : y + 3, x - 2 : x + 3] += 5000

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

        for x, y in centroids:
            image[y - 2 : y + 3, x - 2 : x + 3] += 5000

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
        from PiFinder.sqm.noise_floor import NoiseFloorEstimator

        estimator = NoiseFloorEstimator(camera_type="imx296_processed")
        # imx296_processed has read_noise=1.5, dark_current=0.0

        noise = estimator._estimate_temporal_noise(exposure_sec=1.0)

        # With dark_current=0, temporal_noise = read_noise = 1.5
        assert noise == pytest.approx(1.5, abs=0.01)

    def test_noise_floor_uses_theory_when_dark_pixels_below_bias(self):
        """Test that theory is used when dark pixels are impossibly low."""
        from PiFinder.sqm.noise_floor import NoiseFloorEstimator

        estimator = NoiseFloorEstimator(camera_type="imx296_processed")
        # bias_offset for imx296_processed is 6.0

        # Create image with all pixels below bias offset (impossible in reality)
        image = np.full((100, 100), 3.0, dtype=np.float32)

        noise_floor, _ = estimator.estimate_noise_floor(image, exposure_sec=0.5)

        # Should use theoretical floor since dark pixels (3.0) < bias (6.0)
        assert noise_floor >= estimator.profile.bias_offset

    def test_noise_floor_uses_measured_when_valid(self):
        """Test that measured dark pixels are used when valid."""
        from PiFinder.sqm.noise_floor import NoiseFloorEstimator

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
        from PiFinder.sqm.noise_floor import NoiseFloorEstimator

        estimator = NoiseFloorEstimator(camera_type="imx296_processed")

        # Even with weird inputs, should never go below bias
        image = np.full((100, 100), 100.0, dtype=np.float32)

        noise_floor, _ = estimator.estimate_noise_floor(image, exposure_sec=0.5)

        assert noise_floor >= estimator.profile.bias_offset

    def test_history_smoothing_after_multiple_estimates(self):
        """Test that history smoothing kicks in after 5+ estimates."""
        from PiFinder.sqm.noise_floor import NoiseFloorEstimator

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
        from PiFinder.sqm.noise_floor import NoiseFloorEstimator

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
        from PiFinder.sqm.noise_floor import NoiseFloorEstimator

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
        from PiFinder.sqm.noise_floor import NoiseFloorEstimator

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
        from PiFinder.sqm.noise_floor import NoiseFloorEstimator

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
        from PiFinder.sqm.noise_floor import NoiseFloorEstimator

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
