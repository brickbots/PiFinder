"""
Unit tests for the chart's center-object selection (ADR 0031).

Tests the tracker and the readout string builder directly. Both live in
``PiFinder.ui.center_object`` rather than ``ui/chart.py`` precisely so they can
be tested: the chart itself needs ``hip_main.dat``, which is git-ignored and
doesn't ship.
"""

import pytest

from PiFinder.composite_object import CompositeObject
from PiFinder.ui.center_object import (
    STICKY_MARGIN,
    CenterObjectTracker,
    center_object_text,
)

# The chart's own geometry, so the numbers here read like the real thing.
BOUNDS = (128, 128)
CENTER = (64, 64)


def obj(object_id, catalog_code="NGC", sequence=1, names=None):
    return CompositeObject(
        object_id=object_id,
        catalog_code=catalog_code,
        sequence=sequence,
        names=names or [],
    )


@pytest.mark.unit
class TestCenterObjectTracker:
    def test_nearest_marker_wins(self):
        near, far = obj(1), obj(2)
        tracker = CenterObjectTracker()

        picked = tracker.update([(far, 64, 100), (near, 64, 70)], CENTER, BOUNDS)

        assert picked is near
        assert tracker.changed is True
        assert tracker.center_distance == pytest.approx(6)
        assert tracker.center_xy == (64, 70)

    def test_ranked_is_nearest_first(self):
        a, b, c = obj(1), obj(2), obj(3)
        tracker = CenterObjectTracker()

        tracker.update([(c, 64, 104), (a, 64, 66), (b, 64, 84)], CENTER, BOUNDS)

        assert tracker.ranked == [a, b, c]

    def test_hysteresis_holds_against_a_ten_percent_rival(self):
        """A rival only 10% closer doesn't clear the 15% margin."""
        held, rival = obj(1), obj(2)
        tracker = CenterObjectTracker()
        tracker.update([(held, 64, 84)], CENTER, BOUNDS)  # 20px out
        assert tracker.center_object is held

        # Rival at 18px: 10% closer, short of the 15% margin.
        picked = tracker.update([(held, 64, 84), (rival, 64, 82)], CENTER, BOUNDS)

        assert picked is held
        assert tracker.changed is False
        assert tracker.center_distance == pytest.approx(20)

    def test_hysteresis_yields_to_a_twenty_percent_rival(self):
        held, rival = obj(1), obj(2)
        tracker = CenterObjectTracker()
        tracker.update([(held, 64, 84)], CENTER, BOUNDS)  # 20px out

        # Rival at 16px: 20% closer, so it clears the margin.
        picked = tracker.update([(held, 64, 84), (rival, 64, 80)], CENTER, BOUNDS)

        assert picked is rival
        assert tracker.changed is True
        assert tracker.center_distance == pytest.approx(16)

    def test_margin_is_a_fraction_so_it_scales_with_zoom(self):
        """The same relative gap decides the same way at any distance."""
        held, rival = obj(1), obj(2)
        tracker = CenterObjectTracker()
        tracker.update([(held, 64, 124)], CENTER, BOUNDS)  # 60px out

        # Rival at 48px: 20% closer, the same relative gap that won at 20px.
        picked = tracker.update([(held, 64, 124), (rival, 64, 112)], CENTER, BOUNDS)

        assert picked is rival

    def test_off_screen_candidates_are_excluded(self):
        off, on = obj(1), obj(2)
        tracker = CenterObjectTracker()

        # ``off`` is nearer the center in raw pixels but sits above the top
        # edge, so it isn't a candidate at all.
        picked = tracker.update([(off, 64, -5), (on, 64, 100)], CENTER, BOUNDS)

        assert picked is on
        assert tracker.ranked == [on]

    def test_bounds_are_half_open(self):
        """x == width is off screen; x == 0 is on it."""
        edge, corner = obj(1), obj(2)
        tracker = CenterObjectTracker()

        tracker.update([(edge, 128, 64), (corner, 0, 64)], CENTER, BOUNDS)

        assert tracker.ranked == [corner]

    def test_empty_candidate_set_clears_the_readout(self):
        tracker = CenterObjectTracker()
        tracker.update([(obj(1), 64, 70)], CENTER, BOUNDS)

        picked = tracker.update([], CENTER, BOUNDS)

        assert picked is None
        assert tracker.center_object is None
        assert tracker.center_xy is None
        assert tracker.center_distance is None
        assert tracker.ranked == []
        assert tracker.changed is True

    def test_empty_set_twice_reports_no_further_change(self):
        tracker = CenterObjectTracker()
        tracker.update([], CENTER, BOUNDS)

        tracker.update([], CENTER, BOUNDS)

        assert tracker.changed is False

    def test_current_object_vanishing_hands_the_line_to_the_nearest(self):
        """No incumbent to be sticky about, so no margin applies."""
        gone, remaining = obj(1), obj(2)
        tracker = CenterObjectTracker()
        tracker.update([(gone, 64, 66)], CENTER, BOUNDS)

        picked = tracker.update([(remaining, 64, 124)], CENTER, BOUNDS)

        assert picked is remaining
        assert tracker.changed is True

    def test_current_object_going_off_screen_hands_the_line_over(self):
        held, rival = obj(1), obj(2)
        tracker = CenterObjectTracker()
        tracker.update([(held, 64, 66), (rival, 64, 124)], CENTER, BOUNDS)
        assert tracker.center_object is held

        picked = tracker.update([(held, 64, 200), (rival, 64, 124)], CENTER, BOUNDS)

        assert picked is rival

    def test_holding_the_same_pick_reports_no_change(self):
        held = obj(1)
        tracker = CenterObjectTracker()
        tracker.update([(held, 64, 70)], CENTER, BOUNDS)

        tracker.update([(held, 64, 72)], CENTER, BOUNDS)

        assert tracker.changed is False
        assert tracker.center_xy == (64, 72)

    def test_identity_is_object_id_not_instance(self):
        """The chart hands in fresh CompositeObjects from each radius query."""
        tracker = CenterObjectTracker()
        tracker.update([(obj(1), 64, 70)], CENTER, BOUNDS)

        tracker.update([(obj(1), 64, 71)], CENTER, BOUNDS)

        assert tracker.changed is False

    def test_reset_clears_everything(self):
        tracker = CenterObjectTracker()
        tracker.update([(obj(1), 64, 70)], CENTER, BOUNDS)

        tracker.reset()

        assert tracker.center_object is None
        assert tracker.ranked == []
        assert tracker.changed is True

    def test_a_zero_margin_makes_every_rival_win(self):
        held, rival = obj(1), obj(2)
        tracker = CenterObjectTracker(sticky_margin=0)
        tracker.update([(held, 64, 84)], CENTER, BOUNDS)

        picked = tracker.update([(held, 64, 84), (rival, 64, 83)], CENTER, BOUNDS)

        assert picked is rival

    def test_sticky_margin_default(self):
        assert CenterObjectTracker().sticky_margin == STICKY_MARGIN


@pytest.mark.unit
class TestCenterObjectText:
    def test_designator_plus_first_common_name(self):
        assert (
            center_object_text(
                obj(1, "NGC", 7000, names=["North America Nebula", "Caldwell 20"])
            )
            == "NGC 7000 North America Nebula"
        )

    def test_designator_only_when_there_are_no_names(self):
        assert center_object_text(obj(1, "NGC", 7000)) == "NGC 7000"

    def test_a_name_that_repeats_the_designator_is_deduped(self):
        """'M 45' must not render as 'M 45 M45'."""
        assert center_object_text(obj(1, "M", 45, names=["M45"])) == "M 45"

    def test_dedup_falls_through_to_the_next_real_name(self):
        assert (
            center_object_text(obj(1, "M", 45, names=["M45", "Pleiades"]))
            == "M 45 Pleiades"
        )

    def test_planets_show_their_own_name_once(self):
        """PL objects use names[0] as the designator, so it can't repeat."""
        assert center_object_text(obj(1, "PL", 4, names=["Mars"])) == "Mars"
