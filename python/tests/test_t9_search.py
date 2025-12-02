import sys
import types

import pytest

# Avoid expensive ephemeris downloads triggered during PiFinder.calc_utils import
stub_calc_utils = types.ModuleType("PiFinder.calc_utils")
stub_calc_utils.FastAltAz = None
stub_calc_utils.sf_utils = None
sys.modules["PiFinder.calc_utils"] = stub_calc_utils

from PiFinder.catalogs import Catalogs, KEYPAD_DIGIT_TO_CHARS, LETTER_TO_DIGIT_MAP


class DummyObject:
    def __init__(self, names, catalog_code="TST", sequence=1):
        self.names = names
        self.catalog_code = catalog_code
        self.sequence = sequence


class DummyCatalog:
    def __init__(self, catalog_code, objects):
        self.catalog_code = catalog_code
        self._objects = objects

    def is_selected(self):
        return True

    def get_objects(self):
        return self._objects


@pytest.mark.unit
def test_letter_mapping_uses_keypad_layout():
    # spot-check the non-conventional keypad mapping
    assert LETTER_TO_DIGIT_MAP["t"] == "1"
    assert LETTER_TO_DIGIT_MAP["v"] == "1"
    assert LETTER_TO_DIGIT_MAP["m"] == "5"
    assert LETTER_TO_DIGIT_MAP["'"] == "3"
    # ensure every keypad character is represented in the mapping
    for digit, chars in KEYPAD_DIGIT_TO_CHARS.items():
        for char in chars:
            assert LETTER_TO_DIGIT_MAP[char] == digit


@pytest.mark.unit
def test_search_by_t9_matches_objects():
    objects = [
        DummyObject(["Vega"], sequence=1),
        DummyObject(["M31", "Andromeda"], sequence=2),
        DummyObject(["Polaris"], sequence=3),
    ]
    catalogs = Catalogs([DummyCatalog("TST", objects)])

    # Vega -> v(1)e(8)g(9)a(7)
    vega_results = catalogs.search_by_t9("1897")
    assert len(vega_results) == 1
    assert vega_results[0].sequence == 1

    # M31 -> m(5)3(3)1(1)
    m31_results = catalogs.search_by_t9("531")
    assert len(m31_results) == 1
    assert m31_results[0].sequence == 2

    # No matches should return an empty list
    assert catalogs.search_by_t9("9999") == []
