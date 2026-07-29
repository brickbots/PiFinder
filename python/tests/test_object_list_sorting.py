"""Object-list sorting for general and solar-system metadata."""

import datetime
from unittest.mock import Mock

import pytest

import PiFinder.i18n  # noqa: F401
from PiFinder.composite_object import CompositeObject, MagnitudeObject
from PiFinder.ui.object_list import SortOrder, UIObjectList, _sort_objects


def obj(sequence, mag, distance=None, opposition=None):
    return CompositeObject(
        catalog_code="MP",
        sequence=sequence,
        mag=MagnitudeObject([mag]),
        earth_distance_au=distance,
        opposition_date=opposition,
    )


@pytest.mark.unit
def test_brightest_sort_is_generic():
    objects = [obj(1, 12.0), obj(2, 7.0), obj(3, 10.0)]
    assert [item.sequence for item in _sort_objects(objects, SortOrder.BRIGHTEST)] == [
        2,
        3,
        1,
    ]


@pytest.mark.unit
def test_earth_distance_sort_puts_unknown_last():
    objects = [obj(1, 1, 2.5), obj(2, 1, None), obj(3, 1, 0.4)]
    assert [
        item.sequence for item in _sort_objects(objects, SortOrder.EARTH_DISTANCE)
    ] == [3, 1, 2]


@pytest.mark.unit
def test_opposition_sort_puts_unknown_last():
    objects = [
        obj(1, 1, opposition=datetime.date(2027, 2, 1)),
        obj(2, 1),
        obj(3, 1, opposition=datetime.date(2026, 9, 1)),
    ]
    assert [item.sequence for item in _sort_objects(objects, SortOrder.OPPOSITION)] == [
        3,
        1,
        2,
    ]


@pytest.mark.unit
def test_automatic_list_resort_does_not_show_toast():
    ui = UIObjectList.__new__(UIObjectList)
    ui.current_sort = SortOrder.CATALOG_SEQUENCE
    ui._menu_items = []
    ui._menu_items_sorted = []
    ui._current_item_index = 0
    ui.message = Mock()
    ui.update = Mock()

    ui.sort(show_message=False)

    ui.message.assert_not_called()
    assert ui.update.called
