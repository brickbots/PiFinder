"""
Unit tests for the numpy catalog filter: ``FastAltAz.radec_to_alt_array``
against the scalar ``radec_to_altaz``, ``CatalogFilter.verdicts`` against a
per-object reference of the filter rules, and ``Catalogs.filter_catalogs``
with a subset of catalogs.
"""

import datetime
import random
from types import SimpleNamespace

import numpy as np
import pytest

from PiFinder.calc_utils import FastAltAz
from PiFinder.catalogs import Catalog, CatalogFilter, Catalogs
from PiFinder.composite_object import CompositeObject, MagnitudeObject

pytestmark = pytest.mark.unit

LAT, LON = 51.2, 4.4
DT = datetime.datetime(2026, 9, 29, 21, 30, tzinfo=datetime.timezone.utc)
TYPES = ["Gx", "OC", "Gb", "PN", "D*", None]
CONSTS = ["And", "Cyg", "Ori", "UMa", "Sgr", None]


class AltAzSharedState:
    def location(self):
        return SimpleNamespace(lat=LAT, lon=LON)

    def datetime(self):
        return DT

    def altaz_ready(self):
        return True


def random_objects(count, seed, catalog_code="TST"):
    rng = random.Random(seed)
    objects = []
    for seq in range(1, count + 1):
        mags = [] if rng.random() < 0.1 else [round(rng.uniform(1, 16), 1)]
        objects.append(
            CompositeObject(
                id=seq,
                object_id=seq,
                ra=rng.uniform(0, 360),
                dec=rng.uniform(-90, 90),
                obj_type=rng.choice(TYPES),
                const=rng.choice(CONSTS),
                catalog_code=catalog_code,
                sequence=seq,
                mag=MagnitudeObject(mags),
                logged=rng.random() < 0.3,
            )
        )
    return objects


def reference_verdict(catalog_filter, fast_aa, obj):
    """The filter rules for one object, with the scalar altitude."""
    if catalog_filter.constellations and obj.const not in (
        catalog_filter.constellations
    ):
        return False
    if catalog_filter.altitude != -1:
        try:
            ra, dec = float(obj.ra), float(obj.dec)
        except TypeError:
            return False
        altitude, _ = fast_aa.radec_to_altaz(ra, dec, alt_only=True)
        if altitude < catalog_filter.altitude:
            return False
    magnitude = catalog_filter.magnitude
    if magnitude is not None and obj.mag.filter_mag > magnitude:
        return False
    if catalog_filter.object_types and obj.obj_type not in (
        catalog_filter.object_types
    ):
        return False
    if catalog_filter.observed == "Yes" and not obj.logged:
        return False
    if catalog_filter.observed == "No" and obj.logged:
        return False
    return True


def test_alt_array_matches_scalar_altitude():
    aa = FastAltAz(LAT, LON, DT)
    rng = np.random.default_rng(1)
    ra = rng.uniform(0, 360, 5000)
    dec = rng.uniform(-90, 90, 5000)
    expected = [aa.radec_to_altaz(r, d, alt_only=True)[0] for r, d in zip(ra, dec)]
    np.testing.assert_allclose(aa.radec_to_alt_array(ra, dec), expected, atol=1e-9)


def test_alt_array_near_horizon_and_nan():
    aa = FastAltAz(LAT, LON, DT)
    # Dec values that put an object at the meridian close to the horizon,
    # on both sides of the -1 deg refraction limit.
    ra = np.full(5, aa.local_siderial_time)
    dec = np.array([LAT - 90 + h for h in (-5.0, -1.01, -0.99, 0.0, 2.0)])
    expected = [aa.radec_to_altaz(r, d, alt_only=True)[0] for r, d in zip(ra, dec)]
    np.testing.assert_allclose(aa.radec_to_alt_array(ra, dec), expected, atol=1e-9)
    assert np.isnan(aa.radec_to_alt_array(np.array([np.nan]), np.array([10.0])))[0]


@pytest.mark.parametrize(
    "criteria",
    [
        {},
        {"altitude": 10},
        {"altitude": 0, "magnitude": 9.5},
        {"magnitude": 12.0, "object_types": ["Gx", "PN"]},
        {"constellations": ["Cyg", "Ori"], "observed": "No"},
        {"observed": "Yes", "altitude": 20, "object_types": ["OC"]},
        {
            "altitude": 30,
            "magnitude": 14.0,
            "object_types": ["Gx", "OC", "D*"],
            "constellations": ["And", "UMa", "Sgr"],
            "observed": "No",
        },
    ],
)
def test_verdicts_match_reference(criteria):
    objects = random_objects(3000, seed=len(criteria))
    catalog_filter = CatalogFilter(shared_state=AltAzSharedState(), **criteria)
    catalog_filter.calc_fast_aa(catalog_filter.shared_state)
    expected = [
        reference_verdict(catalog_filter, catalog_filter.fast_aa, obj)
        for obj in objects
    ]
    assert catalog_filter.verdicts(objects).tolist() == expected


def test_apply_records_verdict_on_objects():
    objects = random_objects(200, seed=7)
    catalog_filter = CatalogFilter(shared_state=AltAzSharedState(), altitude=10)
    passed = catalog_filter.apply(objects)
    assert passed == [obj for obj in objects if obj.last_filtered_result]
    assert 0 < len(passed) < len(objects)
    assert all(obj.last_filtered_time > 0 for obj in objects)


def test_missing_coordinates_fail_altitude_only():
    # Near the pole every object is above 10 deg, so only the bad
    # coordinates can fail the altitude test.
    objects = random_objects(3, seed=3)
    for obj in objects:
        obj.dec = 89.0
    objects[1].ra = None
    objects[2].dec = "not a number"
    with_altitude = CatalogFilter(shared_state=AltAzSharedState(), altitude=10)
    with_altitude.calc_fast_aa(with_altitude.shared_state)
    assert with_altitude.verdicts(objects).tolist() == [True, False, False]

    without_altitude = CatalogFilter(shared_state=AltAzSharedState())
    assert without_altitude.verdicts(objects).tolist() == [True, True, True]


def test_filter_catalogs_subset_filters_only_those():
    small = Catalog("M", "small")
    large = Catalog("WDS", "large")
    small.add_objects(random_objects(20, seed=1, catalog_code="M"))
    large.add_objects(random_objects(500, seed=2, catalog_code="WDS"))
    catalogs = Catalogs([small, large])
    catalogs.set_catalog_filter(
        CatalogFilter(shared_state=AltAzSharedState(), altitude=10)
    )

    catalogs.filter_catalogs([small])
    assert small.last_filtered > catalogs.catalog_filter.dirty_time
    assert large.last_filtered == 0
    assert small.get_filtered_count() < 20

    catalogs.filter_catalogs()
    assert large.last_filtered > catalogs.catalog_filter.dirty_time
    assert large.get_filtered_count() < 500
