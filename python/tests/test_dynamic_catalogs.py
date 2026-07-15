"""Dynamic catalog identity, refresh retention, and progress-state tests."""

import datetime

import pytest

from PiFinder.asteroid_catalog import AsteroidCatalog
from PiFinder.catalog_base import CatalogState
from PiFinder.catalogs import Catalog
from PiFinder.comet_catalog import CometCatalog
from PiFinder.composite_object import CompositeObject


class ReadySharedState:
    def altaz_ready(self):
        return True

    def datetime(self):
        return datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)


def initialized_catalog(cls, code):
    catalog = cls.__new__(cls)
    Catalog.__init__(catalog, code, "test")
    catalog.shared_state = ReadySharedState()
    catalog._last_state = CatalogState.READY
    catalog._is_downloading = False
    catalog.download_progress = None
    catalog.calculation_progress = None
    catalog.initialized = True
    return catalog


@pytest.mark.unit
def test_asteroid_object_uses_stable_number_and_structured_metadata():
    catalog = initialized_catalog(AsteroidCatalog, "MP")
    asteroid = {
        "number": 4,
        "name": "Vesta",
        "radec": (20.0, 5.0),
        "mag": 6.5,
        "earth_distance": 1.2,
        "sun_distance": 2.2,
        "angular_motion_arcsec_per_hour": 42.3,
        "opposition_kind": "Opposition",
        "opposition_date": datetime.date(2026, 10, 13),
        "peak_magnitude": 6.4,
        "peak_date": datetime.date(2026, 10, 12),
    }
    obj = catalog._make_object(asteroid)
    assert obj.catalog_code == "MP"
    assert obj.obj_type == "AS"
    assert obj.sequence == 4
    assert obj.names == ["Vesta"]
    assert obj.earth_distance_au == 1.2
    assert obj.opposition_date.isoformat() == "2026-10-13"
    assert obj.description.splitlines()[:2] == [
        "Opp: 2026-10-13",
        "Peak 6.4: 2026-10-12",
    ]
    assert obj.description.splitlines()[-1] == 'Motion: 42.3"/h'


@pytest.mark.unit
def test_asteroid_catalog_labels_annual_edition_instead_of_file_age(tmp_path):
    catalog = initialized_catalog(AsteroidCatalog, "MP")
    catalog.data_directory = tmp_path
    (tmp_path / "Soft00Bright-2026.txt").touch()
    assert catalog.get_data_label() == "MPC 2026"


@pytest.mark.unit
def test_asteroid_edition_label_uses_filename_before_gps_time(tmp_path):
    catalog = initialized_catalog(AsteroidCatalog, "MP")
    catalog.data_directory = tmp_path
    catalog.shared_state.datetime = lambda: None
    (tmp_path / "Soft00Bright-2026.txt").touch()
    assert catalog.get_data_label() == "MPC 2026"


@pytest.mark.unit
def test_asteroid_edition_label_is_empty_without_gps_or_file(tmp_path):
    catalog = initialized_catalog(AsteroidCatalog, "MP")
    catalog.data_directory = tmp_path
    catalog.shared_state.datetime = lambda: None
    assert catalog.get_data_label() is None


@pytest.mark.unit
def test_asteroid_source_year_is_not_selected_before_gps(monkeypatch):
    catalog = AsteroidCatalog.__new__(AsteroidCatalog)
    catalog.shared_state = type("NoGpsState", (), {"altaz_ready": lambda self: False})()
    monkeypatch.setattr(
        "PiFinder.asteroid_catalog.asteroids.check_asteroid_download_needed",
        lambda *_args, **_kwargs: pytest.fail("source year selected without GPS"),
    )
    catalog._refresh_sources()


@pytest.mark.unit
def test_populated_asteroid_catalog_reports_download_progress():
    catalog = initialized_catalog(AsteroidCatalog, "MP")
    catalog.add_object(CompositeObject(catalog_code="MP", sequence=4))
    catalog._is_downloading = True
    catalog.download_progress = 42
    status = catalog.get_status()
    assert catalog.get_count() == 1
    assert status.current == CatalogState.DOWNLOADING
    assert status.data == {"progress": 42}


@pytest.mark.unit
def test_comet_refresh_keeps_old_objects_while_downloading(monkeypatch):
    catalog = initialized_catalog(CometCatalog, "CM")
    catalog.add_object(CompositeObject(catalog_code="CM", sequence=1))
    catalog._is_downloading = True
    catalog.download_progress = 33
    status = catalog.get_status()
    assert status.current == CatalogState.DOWNLOADING
    assert status.data == {"progress": 33}
    catalog._is_downloading = False
    catalog.download_progress = None
    monkeypatch.setattr(
        "PiFinder.comet_catalog.comets.check_if_comet_download_needed",
        lambda *_args, **_kwargs: (True, "new data"),
    )

    def download():
        assert catalog.get_count() == 1
        return False

    catalog._download_once = download

    class ImmediateThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("PiFinder.comet_catalog.threading.Thread", ImmediateThread)
    catalog.refresh()
    assert catalog.get_count() == 1
