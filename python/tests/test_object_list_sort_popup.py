"""
The "Sorting by" popup shows only when the user chooses a sort order. A list
that opens or refreshes sorts without it, because the popup covers the menu
slide (UIModule.update_screen skips frames while a popup shows).
"""

from types import SimpleNamespace

import pytest

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401
from PiFinder.composite_object import CompositeObject
from PiFinder.object_sequence import ObjectSequence
from PiFinder.ui.object_list import SortOrder, UIObjectList

pytestmark = pytest.mark.unit


def _object_list():
    module = object.__new__(UIObjectList)
    module.current_sort = SortOrder.CATALOG_SEQUENCE
    module._menu_items = ObjectSequence.from_objects(
        [
            CompositeObject(object_id=1, sequence=1, ra=30.0),
            CompositeObject(object_id=2, sequence=2, ra=10.0),
        ]
    )
    module._current_item_index = 0
    module.messages = []
    module.message = lambda text, timeout=2: module.messages.append(text)
    module.update = lambda *args, **kwargs: None
    return module


def test_a_list_that_opens_or_refreshes_shows_no_popup():
    module = _object_list()
    module.sort()
    assert module.messages == []
    assert [obj.sequence for obj in module._menu_items_sorted] == [1, 2]


def test_a_sort_chosen_in_the_marking_menu_shows_the_popup():
    module = _object_list()
    marking_menu = SimpleNamespace(select_none=lambda: None)
    menu_item = SimpleNamespace(label=_("RA"), selected=False)
    assert module.mm_change_sort(marking_menu, menu_item)
    assert len(module.messages) == 1 and "RA" in module.messages[0]
    assert [obj.sequence for obj in module._menu_items_sorted] == [2, 1]
