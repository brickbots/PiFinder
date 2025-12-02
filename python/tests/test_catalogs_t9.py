import sys
import types

import pytest

pytest.importorskip("pytz")

dummy_calc_utils = types.ModuleType("PiFinder.calc_utils")
dummy_calc_utils.sf_utils = None


class DummyFastAltAz:
    def __init__(self, *args, **kwargs):
        pass


dummy_calc_utils.FastAltAz = DummyFastAltAz
sys.modules["PiFinder.calc_utils"] = dummy_calc_utils
sys.modules["PiFinder.state"] = types.SimpleNamespace(SharedStateObj=None)
sys.modules["PiFinder.db.db"] = types.SimpleNamespace(Database=None)
sys.modules["PiFinder.db.objects_db"] = types.SimpleNamespace(ObjectsDatabase=None)
sys.modules["PiFinder.db.observations_db"] = types.SimpleNamespace(
    ObservationsDatabase=None
)
sys.modules["PiFinder.comets"] = types.SimpleNamespace(
    comet_data_download=lambda path: (False, None), calc_comets=lambda *a, **k: {}
)
sys.modules["PiFinder.config"] = types.SimpleNamespace(Config=type("Config", (), {}))

from PiFinder.catalogs import Catalog, Catalogs
from PiFinder.composite_object import CompositeObject


@pytest.fixture
def sample_catalogs():
    catalog = Catalog("TST", "Test Catalog")
    andromeda = CompositeObject(object_id=1, sequence=1, names=["Andromeda", "M31"])
    barnards = CompositeObject(object_id=2, sequence=2, names=["Barnard's Star", "GJ 699"])
    catalog.add_objects([andromeda, barnards])
    catalogs = Catalogs([catalog])
    return catalogs, andromeda, barnards


def test_search_by_t9_matches_name_prefix(sample_catalogs):
    catalogs, andromeda, barnards = sample_catalogs
    encoded = catalogs._name_to_t9("Andromeda")

    results = catalogs.search_by_t9(encoded[:3])

    assert andromeda in results
    assert barnards not in results


def test_search_by_t9_uses_digits_in_names(sample_catalogs):
    catalogs, _, barnards = sample_catalogs

    encoded = catalogs._name_to_t9("GJ 699")
    assert encoded.endswith("699")

    results = catalogs.search_by_t9(encoded[:4])

    assert barnards in results


def test_search_by_t9_ignores_non_digit_input(sample_catalogs):
    catalogs, andromeda, _ = sample_catalogs
    encoded = catalogs._name_to_t9("Andromeda")

    results = catalogs.search_by_t9(f"-{encoded} ")

    assert andromeda in results
