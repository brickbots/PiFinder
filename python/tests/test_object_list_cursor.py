"""Tests for cursor preservation across object-list refreshes.

refresh_object_list() rebuilds and re-sorts the list (logging with an
observed criterion, altitude staleness, NEAREST re-sorts); the cursor
follows the selected object instead of resetting to the top. If the
selection was filtered out, it falls to the first surviving old
successor — the natural next target — clamping as a last resort.
"""

import pytest

from PiFinder.composite_object import CompositeObject
from PiFinder.ui.object_list import _next_target_index


def _obj(sequence: int, object_id=None, catalog_code: str = "TST"):
    return CompositeObject(
        object_id=sequence if object_id is None else object_id,
        catalog_code=catalog_code,
        sequence=sequence,
    )


@pytest.mark.unit
def test_surviving_selection_stays_selected():
    old = [_obj(1), _obj(2), _obj(3)]
    new = [_obj(2), _obj(3)]
    assert _next_target_index(new, old, 1) == 0


@pytest.mark.unit
def test_reordered_list_follows_object():
    old = [_obj(1), _obj(2), _obj(3)]
    new = [_obj(3), _obj(1), _obj(2)]
    assert _next_target_index(new, old, 1) == 2


@pytest.mark.unit
def test_removed_selection_falls_to_old_successor():
    old = [_obj(1), _obj(2), _obj(3), _obj(4)]
    new = [_obj(1), _obj(3), _obj(4)]
    assert _next_target_index(new, old, 1) == 1  # lands on 3


@pytest.mark.unit
def test_removed_last_item_clamps():
    old = [_obj(1), _obj(2), _obj(3)]
    new = [_obj(1), _obj(2)]
    assert _next_target_index(new, old, 2) == 1  # new last item


@pytest.mark.unit
def test_sibling_listing_is_not_a_match():
    # M 31 and NGC 224 share an object_id, so CompositeObject.__eq__
    # calls them equal — the cursor must not "find" the old selection in
    # a sibling listing.
    old = [_obj(31, object_id=42, catalog_code="M"), _obj(999)]
    new = [_obj(224, object_id=42, catalog_code="NGC"), _obj(999)]
    assert _next_target_index(new, old, 0) == 1  # falls to 999


@pytest.mark.unit
def test_empty_lists_reset_to_top():
    assert _next_target_index([], [_obj(1)], 0) == 0
    assert _next_target_index([_obj(1)], [], 0) == 0
