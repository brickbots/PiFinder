"""
Unit tests for ``ClosestObjectsFinder`` -- both the radius (angular-distance)
query the chart uses to find catalog objects inside the current field, and the
k-NN ``get_closest_objects`` behind the object-list "Nearby" sort.

The BallTree is built from ``[dec_rad, ra_rad]`` rows with the haversine
metric, because sklearn's haversine reads dimension 0 as latitude. Objects that
share a meridian are the one case where the axis order cannot be observed
(the metric degenerates to ``|dec1 - dec2|``), so every ordering assertion here
places objects at *different* RAs and checks against an independently computed
great-circle separation. High-declination cases are included: that is where a
swapped axis order goes most badly wrong. See ADR 0029.
"""

import math

import pytest

from PiFinder.composite_object import CompositeObject
from PiFinder.nearby import ClosestObjectsFinder, great_circle_degrees


def _obj(object_id, ra, dec, catalog_code="NGC"):
    return CompositeObject(
        object_id=object_id, ra=ra, dec=dec, catalog_code=catalog_code
    )


def _separation(ra_a, dec_a, ra_b, dec_b):
    """Great-circle separation in degrees, computed independently of nearby.py."""
    ra_a, dec_a, ra_b, dec_b = (math.radians(v) for v in (ra_a, dec_a, ra_b, dec_b))
    cos_sep = math.sin(dec_a) * math.sin(dec_b) + math.cos(dec_a) * math.cos(
        dec_b
    ) * math.cos(ra_a - ra_b)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


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

    def test_radius_is_angular_not_per_axis_at_high_dec(self):
        # At dec +80 a 10 deg RA offset is only ~1.7 deg on the sky, while a
        # 10 deg dec offset is a full 10 deg. A per-axis or axis-swapped
        # metric cannot get both of these right at once.
        finder = ClosestObjectsFinder()
        pointing = (0.0, 80.0)
        close_in_ra = _obj(1, 10.0, 80.0)
        far_in_dec = _obj(2, 0.0, 70.0)
        finder.calculate_objects_balltree([close_in_ra, far_in_dec])

        assert _separation(*pointing, 10.0, 80.0) < 2.0
        assert _separation(*pointing, 0.0, 70.0) == pytest.approx(10.0)

        result = finder.get_objects_within_radius(*pointing, 5.0)
        assert {o.object_id for o in result} == {1}


@pytest.mark.unit
class TestGetClosestObjects:
    def test_ranks_by_true_angular_separation(self):
        # The case that exposes a swapped (lat, lon) axis order: object 1 is
        # genuinely closest, but is 10 deg away in RA while object 2 is 10 deg
        # away in dec. Swapping the axes ranks object 2 first.
        finder = ClosestObjectsFinder()
        pointing = (0.0, 60.0)
        objects = [
            _obj(1, 10.0, 60.0),  # ~5.0 deg
            _obj(2, 0.0, 50.0),  # 10.0 deg
            _obj(3, 90.0, 60.0),  # ~41.4 deg
            _obj(4, 180.0, 62.0),  # 58.0 deg
        ]
        finder.calculate_objects_balltree(objects)

        expected = [
            o.object_id
            for o in sorted(objects, key=lambda o: _separation(*pointing, o.ra, o.dec))
        ]
        assert expected == [1, 2, 3, 4]

        result = finder.get_closest_objects(*pointing)
        assert [o.object_id for o in result] == expected

    def test_n_caps_the_result(self):
        finder = ClosestObjectsFinder()
        objects = [_obj(i, i * 3.0, 30.0) for i in range(1, 11)]
        finder.calculate_objects_balltree(objects)

        result = finder.get_closest_objects(3.0, 30.0, n=3)
        assert [o.object_id for o in result] == [1, 2, 3]

    def test_n_larger_than_catalog_is_clamped(self):
        finder = ClosestObjectsFinder()
        finder.calculate_objects_balltree([_obj(1, 0.0, 0.0), _obj(2, 5.0, 5.0)])

        assert len(finder.get_closest_objects(0.0, 0.0, n=100)) == 2

    def test_empty_finder_returns_empty(self):
        assert ClosestObjectsFinder().get_closest_objects(0.0, 0.0) == []


@pytest.mark.unit
class TestGreatCircleDegrees:
    @pytest.mark.parametrize(
        "ra_a, dec_a, ra_b, dec_b",
        [
            (0.0, 0.0, 0.0, 10.0),
            (0.0, 60.0, 10.0, 60.0),
            (359.5, 0.0, 0.5, 0.0),  # across the RA wrap
            (10.0, 89.0, 190.0, 89.0),  # over the pole
            (12.0, -30.0, 200.0, 45.0),
        ],
    )
    def test_matches_independent_formula(self, ra_a, dec_a, ra_b, dec_b):
        assert great_circle_degrees(ra_a, dec_a, ra_b, dec_b) == pytest.approx(
            _separation(ra_a, dec_a, ra_b, dec_b), abs=1e-9
        )

    def test_ra_wrap_is_a_short_hop_not_a_full_turn(self):
        # The per-axis test this replaces read abs(359.5 - 0.5) == 359.
        assert great_circle_degrees(359.5, 0.0, 0.5, 0.0) == pytest.approx(1.0)

    def test_ra_degrees_shrink_with_declination(self):
        assert great_circle_degrees(0.0, 80.0, 1.0, 80.0) < 0.2
        assert great_circle_degrees(0.0, 0.0, 1.0, 0.0) == pytest.approx(1.0)
