import pytest
import numpy as np
from PIL import Image

from PiFinder.sqm import SQM


@pytest.mark.unit
class TestSQMExtinction:
    """
    Unit tests for SQM atmospheric extinction correction.
    """

    def test_extinction_at_zenith(self):
        """Test that extinction at zenith is exactly 0.28 mag (1.0 airmass)"""
        sqm = SQM()
        extinction = sqm._atmospheric_extinction(90.0)
        assert extinction == pytest.approx(0.28, abs=0.0001)

    def test_extinction_at_45_degrees(self):
        """Test extinction at 45° altitude (airmass ≈ 1.414)"""
        sqm = SQM()
        extinction = sqm._atmospheric_extinction(45.0)
        expected = 0.28 * 1.414213562373095  # 0.28 * sqrt(2)
        assert extinction == pytest.approx(expected, abs=0.001)

    def test_extinction_at_30_degrees(self):
        """Test extinction at 30° altitude (airmass = 2.0)"""
        sqm = SQM()
        extinction = sqm._atmospheric_extinction(30.0)
        assert extinction == pytest.approx(0.56, abs=0.001)  # 0.28 * 2.0

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
        """Test that zenith (90°) has the minimum possible extinction"""
        sqm = SQM()
        zenith_extinction = sqm._atmospheric_extinction(90.0)

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
        """Test the airmass formula: airmass = 1 / sin(altitude)"""
        sqm = SQM()

        # At 90°: airmass should be 1.0
        altitude = 90.0
        airmass = 1.0 / np.sin(np.radians(altitude))
        extinction = sqm._atmospheric_extinction(altitude)
        assert extinction == pytest.approx(0.28 * airmass, abs=0.0001)

        # At 30°: airmass should be 2.0
        altitude = 30.0
        airmass = 1.0 / np.sin(np.radians(altitude))
        extinction = sqm._atmospheric_extinction(altitude)
        assert extinction == pytest.approx(0.28 * airmass, abs=0.0001)
        assert airmass == pytest.approx(2.0, abs=0.001)

        # At 6°: airmass ≈ 9.6 (very close to horizon)
        altitude = 6.0
        airmass = 1.0 / np.sin(np.radians(altitude))
        extinction = sqm._atmospheric_extinction(altitude)
        assert extinction == pytest.approx(0.28 * airmass, abs=0.001)


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
            altitude_deg=90.0,
        )

        # Should return tuple
        assert isinstance(result, tuple)
        assert len(result) == 2

        # First element should be float or None
        assert isinstance(result[0], (float, type(None)))

        # Second element should be dict
        assert isinstance(result[1], dict)

    def test_calculate_with_bias_image(self):
        """Test that bias_image is used for pedestal calculation"""
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

        # Create bias image with known pedestal value
        bias_image_pil = Image.new("L", (512, 512), 50)
        bias_image = np.array(bias_image_pil)

        for x, y in centroids:
            image[y - 2 : y + 3, x - 2 : x + 3] += 5000

        _, details = sqm.calculate(
            centroids=centroids,
            solution=solution,
            image=image,
            bias_image=bias_image,
            altitude_deg=90.0,
        )

        # Check that pedestal was calculated from bias image
        assert "pedestal" in details
        assert details["pedestal"] == pytest.approx(50.0, abs=1.0)
        assert details["pedestal_source"] == "bias_image"

    def test_calculate_extinction_applied(self):
        """Test that extinction correction is applied to final SQM value"""
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
        sqm_zenith, details_zenith = sqm.calculate(
            centroids=centroids,
            solution=solution,
            image=image,
            altitude_deg=90.0,
        )

        # Calculate at 30° (2× airmass)
        sqm_30deg, details_30deg = sqm.calculate(
            centroids=centroids,
            solution=solution,
            image=image,
            altitude_deg=30.0,
        )

        # Check extinction values
        assert details_zenith["extinction_correction"] == pytest.approx(0.28, abs=0.001)
        assert details_30deg["extinction_correction"] == pytest.approx(0.56, abs=0.001)

        # Raw SQM should be the same (same image, same stars)
        assert details_zenith["sqm_raw"] == pytest.approx(
            details_30deg["sqm_raw"], abs=0.001
        )

        # Final SQM should differ by extinction difference
        extinction_diff = (
            details_30deg["extinction_correction"]
            - details_zenith["extinction_correction"]
        )
        sqm_diff = sqm_30deg - sqm_zenith
        assert sqm_diff == pytest.approx(extinction_diff, abs=0.001)

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
