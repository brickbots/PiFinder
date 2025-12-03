import sys
import types

import pytest


@pytest.fixture()
def catalogs_api(monkeypatch):
    """Provide catalog helpers while isolating the calc_utils stub."""

    # Avoid expensive ephemeris downloads triggered during PiFinder.calc_utils import
    stub_calc_utils = types.ModuleType("PiFinder.calc_utils")
    stub_calc_utils.FastAltAz = None
    stub_calc_utils.sf_utils = None
    monkeypatch.setitem(sys.modules, "PiFinder.calc_utils", stub_calc_utils)

    # Avoid optional timezone dependency required by the catalogs module
    stub_pytz = types.ModuleType("pytz")
    stub_pytz.timezone = lambda name: name
    stub_pytz.utc = "UTC"
    monkeypatch.setitem(sys.modules, "pytz", stub_pytz)

    # Avoid optional dataclasses JSON dependency required by config/equipment imports
    stub_dataclasses_json = types.ModuleType("dataclasses_json")

    def dataclass_json(cls=None, **_kwargs):
        def decorator(inner_cls):
            return inner_cls

        return decorator(cls) if cls is not None else decorator

    stub_dataclasses_json.dataclass_json = dataclass_json
    monkeypatch.setitem(sys.modules, "dataclasses_json", stub_dataclasses_json)

    # Avoid optional numpy dependency pulled in via CompositeObject
    stub_numpy = types.ModuleType("numpy")
    stub_numpy.array = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "numpy", stub_numpy)

    # Avoid timezone lookup dependency required by SharedState
    stub_timezonefinder = types.ModuleType("timezonefinder")

    class _TimezoneFinder:
        def timezone_at(self, **_kwargs):
            return "UTC"

    stub_timezonefinder.TimezoneFinder = _TimezoneFinder
    monkeypatch.setitem(sys.modules, "timezonefinder", stub_timezonefinder)

    # Avoid skyfield dependency pulled in by comets module
    stub_skyfield = types.ModuleType("skyfield")
    stub_skyfield_data = types.ModuleType("skyfield.data")
    stub_skyfield_constants = types.ModuleType("skyfield.constants")
    stub_skyfield_data.mpc = types.SimpleNamespace(COMET_URL="")
    stub_skyfield_constants.GM_SUN_Pitjeva_2005_km3_s2 = 0
    monkeypatch.setitem(sys.modules, "skyfield", stub_skyfield)
    monkeypatch.setitem(sys.modules, "skyfield.data", stub_skyfield_data)
    monkeypatch.setitem(sys.modules, "skyfield.constants", stub_skyfield_constants)

    from PiFinder import catalogs as catalogs_module

    return catalogs_module.Catalogs, catalogs_module.KEYPAD_DIGIT_TO_CHARS, catalogs_module.LETTER_TO_DIGIT_MAP


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
def test_letter_mapping_uses_keypad_layout(catalogs_api):
    _, KEYPAD_DIGIT_TO_CHARS, LETTER_TO_DIGIT_MAP = catalogs_api
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
def test_search_by_t9_matches_objects(catalogs_api):
    Catalogs, _, _ = catalogs_api
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


@pytest.mark.unit
def test_search_by_t9_uses_cached_digits(monkeypatch, catalogs_api):
    Catalogs, _, _ = catalogs_api
    objects = [DummyObject(["Vega"], sequence=1)]
    catalogs = Catalogs([DummyCatalog("TST", objects)])

    call_count = 0
    original = Catalogs._name_to_t9_digits

    def counting(self, name):
        nonlocal call_count
        call_count += 1
        return original(self, name)

    monkeypatch.setattr(Catalogs, "_name_to_t9_digits", counting)

    catalogs.search_by_t9("1")
    first_count = call_count

    # Subsequent searches should use cached digit strings
    catalogs.search_by_t9("18")
    assert call_count == first_count


@pytest.mark.unit
def test_search_by_t9_cache_invalidation_on_catalog_change(monkeypatch, catalogs_api):
    Catalogs, _, _ = catalogs_api
    objects = [DummyObject(["Vega"], sequence=1)]
    dummy_catalog = DummyCatalog("TST", objects)
    catalogs = Catalogs([dummy_catalog])

    catalogs.search_by_t9("1897")

    new_object = DummyObject(["Deneb"], sequence=2)
    dummy_catalog._objects.append(new_object)

    # Update tracker to ensure cache rebuild triggers conversion for new object
    call_count = 0
    original = Catalogs._name_to_t9_digits

    def counting(self, name):
        nonlocal call_count
        call_count += 1
        return original(self, name)

    monkeypatch.setattr(Catalogs, "_name_to_t9_digits", counting)

    results = catalogs.search_by_t9("88587")

    assert any(obj.sequence == 2 for obj in results)
    assert call_count > 0
