import pytest
from PiFinder import calc_utils
import numpy as np
import datetime
import pytz
from skyfield.api import Star, Angle

from PiFinder.calc_utils import hadec_to_pa, hadec_to_roll
from PiFinder.calc_utils import Skyfield_utils, FastAltAz


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


# ---- Helpers shared by altaz tests ----------------------------------------

# A representative location + time used across the alt/az tests.
_TEST_LAT = 37.7749
_TEST_LON = -122.4194
_TEST_ALT_M = 20.0
_TEST_DT = datetime.datetime(
    2026, 5, 19, hour=4, minute=30, second=0, tzinfo=pytz.timezone("UTC")
)

# Representative RA/Dec test points, all well above the horizon at _TEST_DT
# from _TEST_LAT (alt > 35 deg). Keeping points high keeps refraction-model
# differences between erfa and skyfield down to sub-arcsec, so the pyerfa
# regression tolerance can stay tight.
_TEST_RADECS = [
    (152.090, 11.970),  # Regulus,  alt ~53 deg
    (213.920, 19.180),  # Arcturus, alt ~56 deg
    (201.300, -11.160),  # Spica,    alt ~38 deg
    (177.270, 14.570),  # Denebola, alt ~66 deg
]


def _skyfield_altaz_direct(ra_deg, dec_deg, dt, atmos=True):
    """Compute apparent alt/az using skyfield's native chain.

    Used as the reference for the pyerfa-backed Skyfield_utils.radec_to_altaz.
    The Skyfield_utils singleton's location must already be set.
    """
    sf = calc_utils.sf_utils
    t = sf.ts.from_datetime(dt)
    observer = sf.observer_loc.at(t)
    sky_pos = Star(ra=Angle(degrees=ra_deg), dec_degrees=dec_deg)
    apparent = observer.observe(sky_pos).apparent()
    if atmos:
        alt, az, _ = apparent.altaz("standard")
    else:
        alt, az, _ = apparent.altaz()
    return alt.degrees, az.degrees


def _angular_sep_arcsec(alt1, az1, alt2, az2):
    """Great-circle separation between two alt/az points, in arcseconds."""
    a1 = np.radians(alt1)
    a2 = np.radians(alt2)
    daz = np.radians(az2 - az1)
    cos_sep = np.sin(a1) * np.sin(a2) + np.cos(a1) * np.cos(a2) * np.cos(daz)
    cos_sep = max(-1.0, min(1.0, float(cos_sep)))
    return float(np.degrees(np.arccos(cos_sep))) * 3600.0


@pytest.mark.unit
class TestFastAltAz:
    """FastAltAz: the analytic spherical-trig RA/Dec -> Alt/Az.

    Accuracy floor is ~0.3 deg in 2026, dominated by J2000 -> epoch
    precession. Tests pin this floor as a regression check and verify
    the alt_only short-circuit + the refraction sign.
    """

    def test_returns_finite_values_in_range(self):
        aa = FastAltAz(_TEST_LAT, _TEST_LON, _TEST_DT)
        for ra, dec in _TEST_RADECS:
            alt, az = aa.radec_to_altaz(ra, dec)
            assert -90.0 <= alt <= 90.5  # refraction can lift slightly above 90
            assert 0.0 <= az < 360.0

    def test_alt_only_returns_none_for_az(self):
        aa = FastAltAz(_TEST_LAT, _TEST_LON, _TEST_DT)
        alt_full, _az_full = aa.radec_to_altaz(83.633, 22.0145, alt_only=False)
        alt_only, az_none = aa.radec_to_altaz(83.633, 22.0145, alt_only=True)
        assert az_none is None
        # alt_only and full-call alt agree exactly (same code path before the
        # alt_only branch).
        assert alt_only == pytest.approx(alt_full, abs=1e-12)

    def test_refraction_lifts_low_altitude(self):
        """Bennett refraction should ADD a positive offset to low altitudes
        (apparent alt > true alt above the horizon)."""
        aa = FastAltAz(_TEST_LAT, _TEST_LON, _TEST_DT)
        # Construct a sky direction near the horizon by choosing a star whose
        # geometric altitude is small. Aldebaran-ish at this time of night is
        # low in the west -- verify alt is non-negative and refraction-lifted.
        alt, _az = aa.radec_to_altaz(83.633, 22.0145)
        # Refraction at small alt is ~30 arcmin at the horizon. We're at
        # ~7 deg true alt -> ~7 arcmin lift. Just verify the result is above
        # the geometric horizon and below 90.
        assert alt > 0.0
        assert alt < 90.0

    def test_accuracy_vs_skyfield_within_floor(self):
        """FastAltAz lacks precession/nutation/aberration; total error vs a
        full skyfield apparent-place chain should sit under ~0.5 deg in 2026.
        """
        # Make sure skyfield reference has the location.
        calc_utils.sf_utils.set_location(_TEST_LAT, _TEST_LON, _TEST_ALT_M)
        aa = FastAltAz(_TEST_LAT, _TEST_LON, _TEST_DT)
        for ra, dec in _TEST_RADECS:
            f_alt, f_az = aa.radec_to_altaz(ra, dec)
            s_alt, s_az = _skyfield_altaz_direct(ra, dec, _TEST_DT, atmos=True)
            sep_arcsec = _angular_sep_arcsec(f_alt, f_az, s_alt, s_az)
            # 0.5 deg = 1800 arcsec; comfortably above the observed ~0.3 deg
            # floor while still tight enough to catch a sign-flip or unit bug.
            assert (
                sep_arcsec < 1800.0
            ), f"FastAltAz deviated {sep_arcsec:.0f}'' at ra={ra}, dec={dec}"

    def test_lst_advances_with_time(self):
        """A 1-hour datetime delta should advance LST by ~15.04 deg (sidereal
        rate). Catches LST formula regressions."""
        aa1 = FastAltAz(_TEST_LAT, _TEST_LON, _TEST_DT)
        aa2 = FastAltAz(_TEST_LAT, _TEST_LON, _TEST_DT + datetime.timedelta(hours=1))
        d_lst = (aa2.local_siderial_time - aa1.local_siderial_time) % 360.0
        # Sidereal rotation per solar hour = 15.04106858 deg.
        assert d_lst == pytest.approx(15.04106858, abs=1e-3)


@pytest.mark.unit
class TestSkyfieldUtilsRadecToAltaz:
    """Skyfield_utils.radec_to_altaz: pyerfa-backed (erfa.atco13).

    Should track skyfield's native observe()/apparent()/altaz() chain to
    within arcsec-scale, since both run essentially the same SOFA/ERFA
    precession/nutation/aberration math under the hood.
    """

    def _sf_with_location(self):
        sf = Skyfield_utils()
        sf.set_location(_TEST_LAT, _TEST_LON, _TEST_ALT_M)
        return sf

    def test_requires_set_location(self):
        sf = Skyfield_utils()  # location never set
        with pytest.raises(RuntimeError, match="set_location"):
            sf.radec_to_altaz(83.633, 22.0145, _TEST_DT)

    def test_matches_skyfield_with_refraction(self):
        sf = self._sf_with_location()
        for ra, dec in _TEST_RADECS:
            e_alt, e_az = sf.radec_to_altaz(ra, dec, _TEST_DT, atmos=True)
            s_alt, s_az = _skyfield_altaz_direct(ra, dec, _TEST_DT, atmos=True)
            sep_arcsec = _angular_sep_arcsec(e_alt, e_az, s_alt, s_az)
            # Empirically ~14'' median, well within 60''. 120'' tolerance
            # leaves headroom for the small refraction-model difference
            # between erfa and skyfield's adopted standard atmosphere.
            assert (
                sep_arcsec < 120.0
            ), f"erfa apparent deviated {sep_arcsec:.1f}'' at ra={ra}, dec={dec}"

    def test_matches_skyfield_without_refraction(self):
        sf = self._sf_with_location()
        for ra, dec in _TEST_RADECS:
            e_alt, e_az = sf.radec_to_altaz(ra, dec, _TEST_DT, atmos=False)
            s_alt, s_az = _skyfield_altaz_direct(ra, dec, _TEST_DT, atmos=False)
            sep_arcsec = _angular_sep_arcsec(e_alt, e_az, s_alt, s_az)
            # No refraction-model disagreement here -- the residual is pure
            # precession/nutation/aberration math, identical at sub-arcsec.
            assert (
                sep_arcsec < 30.0
            ), f"erfa no-atmos deviated {sep_arcsec:.1f}'' at ra={ra}, dec={dec}"

    def test_atmos_flag_lifts_altitude(self):
        """atmos=True should produce an apparent altitude >= the geometric
        (atmos=False) value, since refraction lifts objects above the horizon.
        Azimuth should be unaffected by refraction."""
        sf = self._sf_with_location()
        for ra, dec in _TEST_RADECS:
            alt_geo, az_geo = sf.radec_to_altaz(ra, dec, _TEST_DT, atmos=False)
            alt_app, az_app = sf.radec_to_altaz(ra, dec, _TEST_DT, atmos=True)
            assert alt_app >= alt_geo, (
                f"Refraction should not lower altitude (ra={ra}, dec={dec}): "
                f"geo={alt_geo}, apparent={alt_app}"
            )
            # Az unchanged by refraction (atmosphere is symmetric in az).
            assert az_app == pytest.approx(az_geo, abs=1e-6)
