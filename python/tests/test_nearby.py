"""
Unit tests for ``ClosestObjectsFinder.get_objects_within_radius`` -- the
radius (angular-distance) query the chart uses to find catalog objects that
fall inside the current field, distinct from the k-NN ``get_closest_objects``
used by the object-list "Nearby" sort.

The BallTree is built from ``[ra_rad, dec_rad]`` rows with the haversine
metric (the pre-existing convention). Along the ``ra=0`` meridian the haversine
distance reduces to exactly ``|dec|`` in radians, so these tests place objects
at ``ra=0`` and vary dec to assert an exact great-circle radius in degrees.
"""

import pytest

from PiFinder.composite_object import CompositeObject
from PiFinder.nearby import ClosestObjectsFinder


def _obj(object_id, ra, dec, catalog_code="NGC"):
    return CompositeObject(
        object_id=object_id, ra=ra, dec=dec, catalog_code=catalog_code
    )


@pytest.mark.unit
class TestGetObjectsWithinRadius:
    def test_empty_finder_returns_empty(self):
        finder = ClosestObjectsFinder()
        assert finder.get_objects_within_radius(10.0, 20.0, 5.0) == []

    def test_empty_object_set_returns_empty(self):
        finder = ClosestObjectsFinder()
        finder.calculate_objects_balltree([])
        assert finder.get_objects_within_radius(10.0, 20.0, 5.0) == []

    def test_returns_only_objects_within_radius(self):
        finder = ClosestObjectsFinder()
        center = _obj(1, 0.0, 0.0)
        near = _obj(2, 0.0, 2.0)  # 2 deg away
        far = _obj(3, 0.0, 20.0)  # 20 deg away
        finder.calculate_objects_balltree([center, near, far])

        result = finder.get_objects_within_radius(0.0, 0.0, 5.0)
        assert {o.object_id for o in result} == {1, 2}

    def test_radius_boundary_is_great_circle_degrees(self):
        finder = ClosestObjectsFinder()
        center = _obj(1, 0.0, 0.0)
        five_north = _obj(2, 0.0, 5.0)  # exactly 5 deg away
        finder.calculate_objects_balltree([center, five_north])

        # radius just under 5 deg excludes it, just over includes it
        assert {
            o.object_id for o in finder.get_objects_within_radius(0.0, 0.0, 4.0)
        } == {1}
        assert {
            o.object_id for o in finder.get_objects_within_radius(0.0, 0.0, 6.0)
        } == {1, 2}

    def test_deduplicates_by_object_id_with_catalog_precedence(self):
        # Same object_id via M and NGC listings at the same coords; the M
        # listing wins (deduplicate_objects precedence) and only one survives.
        finder = ClosestObjectsFinder()
        ngc = _obj(1, 0.0, 0.0, catalog_code="NGC")
        messier = _obj(1, 0.0, 0.0, catalog_code="M")
        finder.calculate_objects_balltree([ngc, messier])

        result = finder.get_objects_within_radius(0.0, 0.0, 1.0)
        assert len(result) == 1
        assert result[0].catalog_code == "M"
