"""The filter magnitude of an object with several magnitudes.

MagnitudeObject.filter_mag is the one value the catalog filter compares. It
is the brightest magnitude, so a double filters by its primary and a
variable by its maximum (#670, mrosseel's review of #683).
"""

import json

import pytest

from PiFinder.catalogs import Catalog, CatalogFilter
from PiFinder.composite_object import CompositeObject, MagnitudeObject


class _NoLocation:
    def location(self):
        return None

    def datetime(self):
        return None

    def altaz_ready(self):
        return False


@pytest.mark.unit
@pytest.mark.parametrize(
    "mags, filter_mag",
    [
        ([0.6, 9.5], 0.6),  # SAC's Vega: the primary, not 5.05
        ([9.5, 0.6], 0.6),  # the order does not matter
        ([4.86, 7.32], 4.86),  # a variable's range: its maximum
        ([6.5], 6.5),
        (["6.5", "~12"], 6.5),  # what does not parse is left out
        ([], MagnitudeObject.UNKNOWN_MAG),
        (["?"], MagnitudeObject.UNKNOWN_MAG),
    ],
)
def test_the_filter_magnitude_is_the_brightest(mags, filter_mag):
    assert MagnitudeObject(mags).filter_mag == pytest.approx(filter_mag)


@pytest.mark.unit
def test_the_display_string_is_unchanged():
    assert MagnitudeObject([9.0, 3.5]).calc_two_mag_representation() == "3.5/9.0"
    assert MagnitudeObject([6.5]).calc_two_mag_representation() == "6.5"


@pytest.mark.unit
def test_from_json_recomputes_the_filter_magnitude():
    # A database built before this change stores the mean; a device reads
    # the magnitudes and computes the filter magnitude again.
    stored = json.dumps({"mags": [-1.4, 8.4], "filter_mag": 3.5})
    assert MagnitudeObject.from_json(stored).filter_mag == pytest.approx(-1.4)


@pytest.mark.unit
def test_a_double_passes_the_filter_by_its_primary():
    catalog = Catalog("TST", "test catalog")
    catalog.catalog_filter = CatalogFilter(shared_state=_NoLocation())
    catalog.add_object(
        CompositeObject(
            id=1,
            object_id=1,
            catalog_code="TST",
            sequence=1,
            mag=MagnitudeObject([0.6, 9.5]),
        )
    )
    catalog.catalog_filter.magnitude = 4.0
    assert [obj.sequence for obj in catalog.filter_objects()] == [1]
