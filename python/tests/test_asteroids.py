"""Asteroid source parsing, propagation, photometry, and apparition tests."""

import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN
from skyfield.data import mpc

import PiFinder.asteroids as asteroids
from PiFinder.calc_utils import sf_utils


FIXTURE = Path(__file__).parent / "data" / "asteroids_fixture.txt"
DT = datetime(2026, 7, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def observer():
    sf_utils.set_location(50.85, 4.35, 50.0)


def angular_separation_arcsec(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    a = (
        math.sin((d2 - d1) / 2) ** 2
        + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2) ** 2
    )
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a)))) * 3600.0


@pytest.mark.unit
def test_loads_standard_mpcorb_file_with_stable_numbers():
    dataframe = asteroids.load_asteroids_dataframe([FIXTURE])
    assert len(dataframe) == 10
    assert list(dataframe.number[:4]) == [1, 2, 3, 4]
    assert dataframe.number.iloc[-1] == 152637
    assert asteroids.minor_planet_name(dataframe.designation.iloc[0]) == "Ceres"
    assert asteroids.minor_planet_name(dataframe.designation.iloc[-1]) == "152637"


@pytest.mark.unit
def test_vectorized_positions_match_skyfield_per_object_oracle():
    dataframe = asteroids.load_asteroids_dataframe([FIXTURE]).iloc[:8]
    calculated = asteroids._calculate_dataframe(
        dataframe, DT, include_apparitions=False
    )
    time = sf_utils.ts.from_datetime(DT)
    sun = sf_utils.eph["sun"]
    for _, row in dataframe.iterrows():
        asteroid = sun + mpc.mpcorb_orbit(row, sf_utils.ts, GM_SUN)
        topocentric = (asteroid - sf_utils.observer_loc).at(time)
        one_hour_later = sf_utils.ts.tt_jd(time.tt + 1.0 / 24.0)
        topocentric_later = (asteroid - sf_utils.observer_loc).at(one_hour_later)
        heliocentric = (asteroid - sun).at(time)
        ra, dec, earth_distance = topocentric.radec(sf_utils.ts.J2000)
        sun_distance = heliocentric.distance()
        item = calculated[int(row.number)]
        separation = angular_separation_arcsec(
            ra.degrees, dec.degrees, item["radec"][0], item["radec"][1]
        )
        assert separation < 0.05
        assert item["earth_distance"] == pytest.approx(earth_distance.au, rel=1e-7)
        assert item["sun_distance"] == pytest.approx(sun_distance.au, rel=1e-7)
        later_ra, later_dec, _ = topocentric_later.radec(sf_utils.ts.J2000)
        oracle_motion = angular_separation_arcsec(
            ra.degrees, dec.degrees, later_ra.degrees, later_dec.degrees
        )
        assert item["angular_motion_arcsec_per_hour"] == pytest.approx(
            oracle_motion, abs=0.01
        )


@pytest.mark.unit
def test_hg_magnitude_is_h_at_unit_distances_and_zero_phase():
    magnitude = asteroids.hg_magnitude(
        np.array([8.5]),
        np.array([0.15]),
        np.array([1.0]),
        np.array([1.0]),
        np.array([0.0]),
    )
    assert magnitude[0] == pytest.approx(8.5)


@pytest.mark.unit
def test_apparition_reports_vesta_opposition_and_nearby_peak():
    dataframe = asteroids.load_asteroids_dataframe([FIXTURE])
    vesta = dataframe[dataframe.number == 4]
    result = asteroids._calculate_dataframe(vesta, DT)[4]
    assert result["opposition_kind"] == "Opposition"
    assert result["opposition_date"].isoformat() == "2026-10-13"
    assert abs((result["peak_date"] - result["opposition_date"]).days) <= 90
    assert result["peak_magnitude"] <= result["mag"]


@pytest.mark.unit
def test_next_apparition_skips_just_passed_day_zero_opposition():
    index, is_opposition = asteroids._next_apparition_index(
        np.array([180.0, 175.0, 160.0, 170.0, 179.0, 170.0])
    )
    assert index == 4
    assert is_opposition


@pytest.mark.unit
def test_next_apparition_skips_day_zero_greatest_elongation():
    index, is_opposition = asteroids._next_apparition_index(
        np.array([120.0, 110.0, 80.0, 100.0, 125.0, 100.0])
    )
    assert index == 4
    assert not is_opposition


@pytest.mark.unit
def test_visibility_cut_rejects_non_finite_and_dim_objects():
    dataframe = asteroids.load_asteroids_dataframe([FIXTURE]).iloc[:2].copy()
    dataframe.loc[dataframe.index[0], "magnitude_H"] = np.nan
    dataframe.loc[dataframe.index[1], "magnitude_H"] = 99.0
    assert asteroids._calculate_dataframe(dataframe, DT) == {}


@pytest.mark.unit
def test_calc_asteroids_without_observer_is_empty():
    saved_location = sf_utils.observer_loc
    saved_last = sf_utils._last_location
    try:
        sf_utils.observer_loc = None
        sf_utils._last_location = None
        assert asteroids.calc_asteroids(DT, [FIXTURE]) == {}
    finally:
        sf_utils.observer_loc = saved_location
        sf_utils._last_location = saved_last
