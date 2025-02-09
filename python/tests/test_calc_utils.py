import pytest
from PiFinder import calc_utils
import numpy as np
import datetime
import pytz

from PiFinder.calc_utils import hadec_to_pa, hadec_to_roll
from PiFinder.calc_utils import Skyfield_utils


@pytest.mark.unit
def test_converters():
    assert calc_utils.ra_to_deg(10, 10, 50) == pytest.approx(152.70833, abs=0.00001)
    assert calc_utils.dec_to_deg(10, 10, 50) == pytest.approx(10.18056, abs=0.00001)
    assert calc_utils.dec_to_dms(80.55) == (80, 32, 59)
    assert calc_utils.ra_to_hms(81.55) == (5, 26, 12)


@pytest.mark.unit
class TestCalcUtils:
    """
    Unit tests for calc_utils.py which does coordinate transformations.
    """

    def test_hadec_to_pa0(self):
        """Unit Test: hadec_to_pa(): For the special case when HA = 0"""
        # Define the inputs:
        ha_deg = 0.0
        lat_deg = 51.0  # Approximately Greenwich Observatory
        dec_degs = [90, 60, 51, 30, 0, -30]

        # At HA = 0, expect pa = 0 or 180 deg
        for dec in dec_degs:
            pa_deg = hadec_to_pa(ha_deg, dec, lat_deg)
            if dec == lat_deg:
                assert pa_deg == pytest.approx(
                    180.0, abs=0.001
                ) or pa_deg == pytest.approx(0.0, abs=0.001), f"Testing: {dec}"
            elif dec > lat_deg:
                assert pa_deg == pytest.approx(180.0, abs=0.001), f"Testing: {dec}"
            else:
                assert pa_deg == pytest.approx(0.0, abs=0.001), f"Testing: {dec}"

    def test_hadec_to_pa(self):
        """Unit Test: haddec_to_pa(): For when HA != 0"""
        # Define the inputs:
        ha_deg = 60.0
        lat_deg = 51.0  # Approximately Greenwich Observatory
        dec_degs = [90, 60, 51, 30, 0, -30]
        # Expected values for +ve HA (exp. values for -ve HA are the -ves)
        expected_pa_degs = [120.00000, 77.9774, 65.8349, 46.5827, 35.0417, 33.2789]

        for dec, expected in zip(dec_degs, expected_pa_degs):
            # +ve HA case:
            pa_deg = hadec_to_pa(ha_deg, dec, lat_deg)
            assert pa_deg == pytest.approx(expected, abs=0.001)
            # -ve HA case (expect -ve values):
            pa_deg = hadec_to_pa(-ha_deg, dec, lat_deg)
            assert pa_deg == pytest.approx(-expected, abs=0.001)

    def test_hadec_to_roll(self):
        """Unit Test: haddec_to_roll()"""
        # Define the inputs:
        lat_deg = 51.0  # Approximately Greenwich Observatory
        ha_degs = [
            60.0,
            60.0,
            60.0,
            60.0,
            60.0,
            60.0,
            -60.0,
            -60.0,
            -60.0,
            -60.0,
            -60.0,
            -60.0,
        ]
        dec_degs = [90, 60, 51, 30, 0, -30, 90, 60, 51, 30, 0, -30]
        # Expected values
        expected_roll_degs = [
            60.0,
            102.0225,
            -65.8349,
            -46.5828,
            -35.0417,
            -33.2790,
            -60.0,
            -102.0226,
            65.8349,
            46.5828,
            35.04173,
            33.27898,
        ]

        for ha, dec, expected in zip(ha_degs, dec_degs, expected_roll_degs):
            roll = hadec_to_roll(ha, dec, lat_deg)
            assert roll == pytest.approx(expected, abs=0.001)

    def test_hadec_to_roll2(self):
        """Unit Test against observed roll data: haddec_to_roll()"""
        # Define the inputs:
        lat_deg = 35.819676052
        ha_hrs = [4.1309, -3.6298, 0.3378]
        dec_degs = [74.0515, 22.2856, 30.3246]
        # Observed values
        observed_roll_degs = [72.0398, 62.6766, -31.3812]

        for ha_hr, dec, observed in zip(ha_hrs, dec_degs, observed_roll_degs):
            ha = ha_hr / 12 * 180  # Convert from hr to deg
            roll = hadec_to_roll(ha, dec, lat_deg)
            # Roll must be within 5 degrees
            assert np.abs(roll - observed) < 5

    # Test Skyfield_utils:

    def test_sf_set_location(self):
        """
        Unit test Skyfield_utils.set_location() and Skyfield_utils.get_latlon()
        setting and reading back latitude & logitude.
        """
        sf = Skyfield_utils()
        # Set observation location
        expected_lat_deg = 35.819676052
        expected_lon_deg = -120.959589646
        expected_alt_deg = 5.959589
        sf.set_location(expected_lat_deg, expected_lon_deg, expected_alt_deg)

        # Check observer location
        lat_deg, lon_deg, alt_deg = sf.get_lat_lon_alt()
        assert lat_deg == pytest.approx(expected_lat_deg, abs=0.001)
        assert lon_deg == pytest.approx(expected_lon_deg, abs=0.001)
        assert alt_deg == pytest.approx(expected_alt_deg, abs=0.001)

    def test_sf_get_lst_hrs(self):
        """
        Unit test Skyfield_utils.get_lst_hrs() against logged data
        during observation.
        """
        sf = Skyfield_utils()
        lat_deg = 35.819676052
        lon_deg = -120.959589646
        sf.set_location(lat_deg, lon_deg, 0)
        dt = datetime.datetime(
            2024, 5, 2, hour=3, minute=39, second=20, tzinfo=pytz.timezone("UTC")
        )
        lst_hrs = sf.get_lst_hrs(dt)

        # There's 20 seconds difference between the LST logged during observatino
        # (below) and the LST calculated from the logged time and location. This
        # corresonds to a 5-arcmin discrepancy.
        expected_lst_hrs = 154.33825506226094 * 12 / 180
        assert lst_hrs == pytest.approx(expected_lst_hrs, abs=0.1)

    def test_sf_ra_to_ha(self):
        """
        Unit test Skyfield_utils.ra_to_ha() against logged data during observation.
        """
        sf = Skyfield_utils()
        lat_deg = 35.819676052
        lon_deg = -120.959589646
        ra_deg = 92.37361818027753
        sf.set_location(lat_deg, lon_deg, 0)
        dt = datetime.datetime(
            2024, 5, 2, hour=3, minute=39, second=20, tzinfo=pytz.timezone("UTC")
        )
        ha_deg = sf.ra_to_ha(ra_deg, dt)

        # There's 20 seconds difference between the LST logged during observatino
        # (below) and the LST calculated from the logged time and location. This
        # is causing the relatively large discrepancy.
        expected_ha_deg = 4.130975792132227 / 12 * 180
        assert ha_deg == pytest.approx(expected_ha_deg, abs=0.1)

    def test_sf_radec_to_roll(self):
        """
        Unit test Skyfield_utils.radec_to_roll() against logged data during
        observation.
        """
        sf = Skyfield_utils()
        lat_deg = 35.819676052
        lon_deg = -120.959589646
        ra_deg = 92.37361818027753
        dec_deg = 74.05157649264223
        sf.set_location(lat_deg, lon_deg, 0)
        dt = datetime.datetime(
            2024, 5, 2, hour=3, minute=39, second=20, tzinfo=pytz.timezone("UTC")
        )

        roll_deg = sf.radec_to_roll(ra_deg, dec_deg, dt)

        # Compare against observed roll
        expected_roll_deg = 72.03989158956631
        assert np.abs(roll_deg - expected_roll_deg) < 2.1
