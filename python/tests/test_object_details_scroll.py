"""Tests for UP/DOWN in object details when catalog listings share a sky object.

CompositeObject equality compares object_id, and several catalog listings can
share one sky object: M 31 and NGC 224, or the Steinicke NGC/IC duplicate pairs
such as NGC 6 and NGC 20. scroll_object has to find its place in the list by
catalog listing; finding it by ``==`` lands on whichever sibling listing comes
first, so scrolling from the second of a pair jumps back to the first and,
where the pair is adjacent, sticks there.

The object list is a plain list from most sources and a NumPy array from the
Nearby sort, so each case runs against both.
"""

import numpy as np
import pytest

# Installs the ``_()`` gettext builtin the UI modules rely on. MUST precede any
# ``PiFinder.ui`` import.
import PiFinder.i18n  # noqa: F401

from PiFinder.composite_object import CompositeObject
from PiFinder.ui.object_details import UIObjectDetails, _listing_index
from PiFinder.ui.object_list import UIObjectList


def _listing(catalog_code: str, sequence: int, object_id: int) -> CompositeObject:
    return CompositeObject(
        object_id=object_id, catalog_code=catalog_code, sequence=sequence
    )


def _as_list(objects):
    return list(objects)


def _as_array(objects):
    # Nearby hands over np.array(objects)[indices]: a 1-D object array.
    array = np.empty(len(objects), dtype=object)
    array[:] = objects
    return array


LIST_KINDS = pytest.mark.parametrize(
    "kind", [_as_list, _as_array], ids=["list", "ndarray"]
)


def _details(object_list, start: int, pass_index: bool = True) -> UIObjectDetails:
    """
    A UIObjectDetails reduced to the state scroll_object reads and writes,
    opened on ``object_list[start]``. ``pass_index`` is whether the caller
    passed "object_index" (UIObjectList does; the chart, recents and the
    coordinate-entry callback don't). Resolves the starting slot the way
    __init__ does.
    """
    details = UIObjectDetails.__new__(UIObjectDetails)
    details.object_list = object_list
    details.object = object_list[start]
    details.object_index = _listing_index(
        object_list, details.object, start if pass_index else None
    )
    details.update_object_info = lambda: None
    details.update = lambda: None
    return details


def _walk(details: UIObjectDetails, direction: int, steps: int) -> list:
    """The listings shown, as (catalog_code, sequence), over ``steps`` presses."""
    shown = [details.object]
    for _ in range(steps):
        details.scroll_object(direction)
        shown.append(details.object)
    return [(obj.catalog_code, obj.sequence) for obj in shown]


def _keys(objects) -> list:
    return [(obj.catalog_code, obj.sequence) for obj in objects]


def _adjacent_pair():
    # RA order: NGC 6 and NGC 20 are one sky object, so they sort together.
    return [
        _listing("NGC", 5, 5),
        _listing("NGC", 6, 6),
        _listing("NGC", 20, 6),
        _listing("NGC", 21, 21),
    ]


def _separated_pair():
    # Catalog order: the pair sits apart, with other listings between.
    return [
        _listing("NGC", 6, 6),
        _listing("NGC", 7, 7),
        _listing("NGC", 8, 8),
        _listing("NGC", 20, 6),
        _listing("NGC", 21, 21),
    ]


def _cross_catalog_pair():
    # "All Filtered" with M and NGC both selected: M 31 and NGC 224.
    return [
        _listing("M", 31, 224),
        _listing("M", 32, 221),
        _listing("NGC", 221, 221),
        _listing("NGC", 224, 224),
    ]


PAIR_LISTS = pytest.mark.parametrize(
    "make_objects",
    [_adjacent_pair, _separated_pair, _cross_catalog_pair],
    ids=["adjacent", "separated", "cross-catalog"],
)


@pytest.mark.unit
@LIST_KINDS
@PAIR_LISTS
@pytest.mark.parametrize("pass_index", [True, False], ids=["index", "no-index"])
def test_scrolling_down_visits_each_listing_once(kind, make_objects, pass_index):
    objects = kind(make_objects())
    details = _details(objects, 0, pass_index)
    assert _walk(details, 1, len(objects) - 1) == _keys(objects)


@pytest.mark.unit
@LIST_KINDS
@PAIR_LISTS
@pytest.mark.parametrize("pass_index", [True, False], ids=["index", "no-index"])
def test_scrolling_up_visits_each_listing_once(kind, make_objects, pass_index):
    objects = kind(make_objects())
    details = _details(objects, len(objects) - 1, pass_index)
    assert _walk(details, -1, len(objects) - 1) == _keys(objects)[::-1]


@pytest.mark.unit
@LIST_KINDS
@pytest.mark.parametrize("pass_index", [True, False], ids=["index", "no-index"])
def test_opening_the_second_of_a_pair_steps_from_it(kind, pass_index):
    objects = kind(_separated_pair())
    details = _details(objects, 3, pass_index)  # NGC 20
    details.scroll_object(1)
    assert _keys([details.object]) == [("NGC", 21)]

    details = _details(objects, 3, pass_index)
    details.scroll_object(-1)
    assert _keys([details.object]) == [("NGC", 8)]


@pytest.mark.unit
@LIST_KINDS
def test_last_listing_holds_without_jumping_to_its_sibling(kind):
    objects = kind(
        [_listing("NGC", 6, 6), _listing("NGC", 7, 7), _listing("NGC", 20, 6)]
    )
    details = _details(objects, 2)  # NGC 20, last in the list
    assert _walk(details, 1, 2) == [("NGC", 20)] * 3


@pytest.mark.unit
@LIST_KINDS
def test_same_listing_twice_is_walked_by_position(kind):
    # An observing list naming M 31 twice resolves both entries to one shared
    # CompositeObject. Only the cursor index tells the two rows apart.
    m31 = _listing("M", 31, 224)
    m33 = _listing("M", 33, 598)
    objects = kind([m31, m33, m31])

    details = _details(objects, 0)
    assert _walk(details, 1, 3) == [("M", 31), ("M", 33), ("M", 31), ("M", 31)]
    assert details.object_index == 2

    details = _details(objects, 2)
    assert _walk(details, -1, 3) == [("M", 31), ("M", 33), ("M", 31), ("M", 31)]
    assert details.object_index == 0


@pytest.mark.unit
@LIST_KINDS
def test_listing_key_is_the_fallback_for_another_instance(kind):
    # The object held is not an instance in the list (it was built apart from
    # it), so identity finds nothing: match its own (catalog_code, sequence),
    # not the sibling listing ahead of it.
    objects = kind(_separated_pair())
    details = _details(objects, 0)
    details.object = _listing("NGC", 20, 6)
    details.object_index = None
    details.scroll_object(1)
    assert _keys([details.object]) == [("NGC", 21)]


@pytest.mark.unit
def test_stale_hint_is_ignored():
    objects = _separated_pair()
    # The slot named holds a different listing, so the hint can't be trusted.
    assert _listing_index(objects, objects[3], hint=0) == 3
    assert _listing_index(objects, objects[3], hint=99) == 3
    assert _listing_index(objects, objects[3], hint=-1) == 3


@pytest.mark.unit
def test_object_not_in_the_list_stays_put():
    objects = _separated_pair()
    details = _details(objects, 0)
    details.object = _listing("IC", 1, 9001)
    details.object_index = None
    details.scroll_object(1)
    assert _keys([details.object]) == [("IC", 1)]


@pytest.mark.unit
def test_object_list_passes_the_row_it_opens():
    m31 = _listing("M", 31, 224)
    object_list = UIObjectList.__new__(UIObjectList)
    object_list._menu_items_sorted = [m31, _listing("M", 33, 598), m31]
    pushed = []
    object_list.add_to_stack = pushed.append

    object_list.show_object_details(2)

    assert pushed[0]["object"] is m31
    assert pushed[0]["object_index"] == 2
