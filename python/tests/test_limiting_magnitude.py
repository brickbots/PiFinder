#!/usr/bin/env python3
"""
Unit tests for limiting magnitude calculations using Feijth & Comello formula
"""

import pytest
from PiFinder.object_images.gaia_chart import GaiaChartGenerator


class TestFeijthComelloFormula:
    """Test the Feijth & Comello limiting magnitude formula"""

    def test_reference_calculation(self):
        """
        Test with Schaefer's reference values

        Reference from astrobasics.de:
        If Schaefer's result is used with mv = 6.04, D = 25, d = 4, M = 400
        and t = 0.54 the following limiting magnitude results: 13.36

        Formula: mg = mv - 2 + 2.5 × log₁₀(√(D² - d²) × M × t)
        """
        mv = 6.04  # Naked eye limiting magnitude
        D = 25.0  # Aperture in cm
        d = 4.0  # Obstruction diameter in cm
        M = 400.0  # Magnification
        t = 0.54  # Transmission

        result = GaiaChartGenerator.feijth_comello_limiting_magnitude(mv, D, d, M, t)

        # Should be 13.36 according to reference (allow 0.1 mag tolerance)
        assert abs(result - 13.36) < 0.1, f"Expected ~13.36, got {result:.2f}"

    def test_unobstructed_telescope(self):
        """Test with no central obstruction (refractor/unobstructed Newtonian)"""
        mv = 6.0
        D = 20.0  # 200mm aperture
        d = 0.0  # No obstruction
        M = 100.0
        t = 0.85

        result = GaiaChartGenerator.feijth_comello_limiting_magnitude(mv, D, d, M, t)

        # Should give reasonable result (12-14 range for 200mm scope)
        assert 10.0 < result < 15.0, f"Result {result:.2f} outside expected range"

    def test_higher_magnification_improves_lm(self):
        """
        Test that higher magnification improves limiting magnitude
        (darkens sky background, improving contrast)
        """
        mv = 6.0
        D = 20.0
        d = 0.0
        t = 0.85

        lm_40x = GaiaChartGenerator.feijth_comello_limiting_magnitude(mv, D, d, 40.0, t)
        lm_100x = GaiaChartGenerator.feijth_comello_limiting_magnitude(mv, D, d, 100.0, t)
        lm_200x = GaiaChartGenerator.feijth_comello_limiting_magnitude(mv, D, d, 200.0, t)

        # Higher magnification should give better (larger number) limiting magnitude
        assert lm_100x > lm_40x, f"100x ({lm_100x:.2f}) should be > 40x ({lm_40x:.2f})"
        assert lm_200x > lm_100x, f"200x ({lm_200x:.2f}) should be > 100x ({lm_100x:.2f})"

    def test_larger_aperture_improves_lm(self):
        """Test that larger aperture improves limiting magnitude"""
        mv = 6.0
        d = 0.0
        M = 100.0
        t = 0.85

        lm_80mm = GaiaChartGenerator.feijth_comello_limiting_magnitude(mv, 8.0, d, M, t)
        lm_150mm = GaiaChartGenerator.feijth_comello_limiting_magnitude(mv, 15.0, d, M, t)
        lm_250mm = GaiaChartGenerator.feijth_comello_limiting_magnitude(mv, 25.0, d, M, t)

        # Larger aperture should give better limiting magnitude
        assert lm_150mm > lm_80mm, f"150mm ({lm_150mm:.2f}) should be > 80mm ({lm_80mm:.2f})"
        assert lm_250mm > lm_150mm, f"250mm ({lm_250mm:.2f}) should be > 150mm ({lm_150mm:.2f})"

    def test_obstruction_reduces_lm(self):
        """Test that central obstruction reduces limiting magnitude"""
        mv = 6.0
        D = 20.0
        M = 100.0
        t = 0.85

        lm_no_obstruction = GaiaChartGenerator.feijth_comello_limiting_magnitude(mv, D, 0.0, M, t)
        lm_with_obstruction = GaiaChartGenerator.feijth_comello_limiting_magnitude(mv, D, 5.0, M, t)

        # Obstruction should reduce limiting magnitude
        assert lm_no_obstruction > lm_with_obstruction, \
            f"Unobstructed ({lm_no_obstruction:.2f}) should be > obstructed ({lm_with_obstruction:.2f})"

    def test_better_transmission_improves_lm(self):
        """Test that better transmission improves limiting magnitude"""
        mv = 6.0
        D = 20.0
        d = 0.0
        M = 100.0

        lm_poor_transmission = GaiaChartGenerator.feijth_comello_limiting_magnitude(mv, D, d, M, 0.50)
        lm_good_transmission = GaiaChartGenerator.feijth_comello_limiting_magnitude(mv, D, d, M, 0.85)

        # Better transmission should give better limiting magnitude
        assert lm_good_transmission > lm_poor_transmission, \
            f"Good transmission ({lm_good_transmission:.2f}) should be > poor ({lm_poor_transmission:.2f})"

    def test_darker_sky_improves_naked_eye_lm(self):
        """
        Test that darker sky (higher mv) improves telescopic limiting magnitude
        Since telescopic LM builds on naked eye LM
        """
        D = 20.0
        d = 0.0
        M = 100.0
        t = 0.85

        lm_bright_sky = GaiaChartGenerator.feijth_comello_limiting_magnitude(5.0, D, d, M, t)
        lm_dark_sky = GaiaChartGenerator.feijth_comello_limiting_magnitude(6.5, D, d, M, t)

        # Darker sky should give better limiting magnitude
        assert lm_dark_sky > lm_bright_sky, \
            f"Dark sky ({lm_dark_sky:.2f}) should be > bright sky ({lm_bright_sky:.2f})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
