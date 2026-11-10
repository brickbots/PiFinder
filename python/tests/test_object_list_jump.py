"""Tests for the object list's jump to a number typed on the keypad.

The number takes as many digits as the list's largest: a Named Stars HIP
number (Nam 118322) or a WDS sequence has six, Messier's four at least.
"""

import types

import pytest

from PiFinder.composite_object import CompositeObject
from PiFinder.ui.object_list import CatalogSequence, UIObjectList


def _list(*sequences):
    """Just enough of a UIObjectList for key_number."""
    jumped = []
    return types.SimpleNamespace(
        jump_input_display=False,
        jump_to_number=CatalogSequence(),
        _menu_items_sorted=[
            CompositeObject(object_id=s, catalog_code="Nam", sequence=s)
            for s in sequences
        ],
        scroll_to_sequence=jumped.append,
        update=lambda: None,
        jumped=jumped,
    )


def _type(object_list, digits):
    for digit in digits:
        UIObjectList.key_number(object_list, int(digit))


@pytest.mark.unit
def test_a_six_digit_number_is_typed_whole():
    object_list = _list(677, 91262, 118322)
    _type(object_list, "118322")
    assert object_list.jumped[-1] == 118322
    assert str(object_list.jump_to_number) == "118322"


@pytest.mark.unit
def test_a_short_catalog_keeps_four_digits():
    object_list = _list(1, 31, 110)
    _type(object_list, "31")
    assert str(object_list.jump_to_number) == "--31"
    _type(object_list, "042")
    # The oldest digit drops off past four.
    assert object_list.jump_to_number.object_number == 1042


@pytest.mark.unit
def test_a_leading_zero_opens_no_input():
    object_list = _list(91262)
    _type(object_list, "0")
    assert not object_list.jump_input_display
    assert object_list.jumped == []
