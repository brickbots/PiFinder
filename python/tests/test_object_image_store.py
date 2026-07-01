"""Unit tests for the shared object-image core (ADR 0018)."""

import sqlite3
import types

import pytest

from PiFinder import object_image_store as store


def _obj(catalog_code, sequence, names=()):
    """Minimal stand-in for a CompositeObject for resolution tests."""
    return types.SimpleNamespace(
        catalog_code=catalog_code, sequence=sequence, names=list(names)
    )


@pytest.mark.unit
class TestLayout:
    def test_bucket_is_last_char(self):
        assert store.image_bucket("NGC224") == "4"
        assert store.image_bucket("M13") == "3"

    def test_local_path_is_sourceless(self):
        assert store.local_image_path("NGC224").endswith("/4/NGC224.jpg")

    def test_cdn_url_is_sourceless(self):
        assert store.cdn_image_url("NGC224") == f"{store.CDN_BASE_URL}/4/NGC224.jpg"


@pytest.mark.unit
class TestResolveImageName:
    def test_primary_stem(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "BASE_IMAGE_PATH", str(tmp_path))
        (tmp_path / "3").mkdir()
        (tmp_path / "3" / "M13.jpg").write_bytes(b"x")
        assert store.resolve_image_name(_obj("M", 13)) == str(
            tmp_path / "3" / "M13.jpg"
        )

    def test_common_name_fallback(self, tmp_path, monkeypatch):
        # M 31's canonical image is published as NGC224; the "NGC 224" common
        # name (whitespace-stripped) is what resolves it on disk.
        monkeypatch.setattr(store, "BASE_IMAGE_PATH", str(tmp_path))
        (tmp_path / "4").mkdir()
        (tmp_path / "4" / "NGC224.jpg").write_bytes(b"x")
        obj = _obj("M", 31, names=["NGC 224", "Andromeda Galaxy"])
        assert store.resolve_image_name(obj) == str(tmp_path / "4" / "NGC224.jpg")

    def test_missing_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "BASE_IMAGE_PATH", str(tmp_path))
        assert store.resolve_image_name(_obj("M", 99, names=["Nope"])) == ""

    def test_does_not_mutate_object(self, tmp_path, monkeypatch):
        # image_name is the DB stem; resolution must not overwrite it with a path.
        monkeypatch.setattr(store, "BASE_IMAGE_PATH", str(tmp_path))
        (tmp_path / "3").mkdir()
        (tmp_path / "3" / "M13.jpg").write_bytes(b"x")
        obj = _obj("M", 13)
        obj.image_name = "M13"
        store.resolve_image_name(obj)
        assert obj.image_name == "M13"


@pytest.fixture
def cursor():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE object_images "
        "(id INTEGER PRIMARY KEY, object_id INTEGER, image_name TEXT, source TEXT)"
    )
    cur.execute(
        "CREATE TABLE catalog_objects "
        "(id INTEGER PRIMARY KEY, object_id INTEGER, catalog_code TEXT, sequence INTEGER)"
    )
    rows_images = [
        (224, "NGC224"),  # M 31 ≡ NGC 224
        (7000, "NGC7000"),  # NGC only
        (500, "WDS500"),  # WDS only -> excluded from "All"
        (9, ""),  # empty image_name -> ignored everywhere
    ]
    cur.executemany(
        "INSERT INTO object_images (object_id, image_name) VALUES (?, ?)", rows_images
    )
    rows_listings = [
        (224, "NGC", 224),
        (224, "M", 31),
        (7000, "NGC", 7000),
        (500, "WDS", 500),
        (9, "M", 9),
    ]
    cur.executemany(
        "INSERT INTO catalog_objects (object_id, catalog_code, sequence) "
        "VALUES (?, ?, ?)",
        rows_listings,
    )
    conn.commit()
    yield cur
    conn.close()


@pytest.mark.unit
class TestWorklist:
    def test_all_excludes_wds_and_empty(self, cursor):
        assert set(store.worklist_for_scope(store.SCOPE_ALL, cursor)) == {
            "NGC224",
            "NGC7000",
        }

    def test_single_catalog_ngc(self, cursor):
        assert set(
            store.worklist_for_scope(store.SCOPE_CATALOG, cursor, catalog_code="NGC")
        ) == {"NGC224", "NGC7000"}

    def test_single_catalog_m_resolves_canonical_stem(self, cursor):
        # Viewing the M listing still maps to the canonical NGC224 stem; the
        # empty-image M 9 listing is excluded.
        assert set(
            store.worklist_for_scope(store.SCOPE_CATALOG, cursor, catalog_code="M")
        ) == {"NGC224"}

    def test_filter_scope_maps_object_ids(self, cursor):
        objects = [types.SimpleNamespace(object_id=224)]
        assert store.worklist_for_scope(
            store.SCOPE_FILTER, cursor, objects=objects
        ) == ["NGC224"]

    def test_list_scope_dedups_and_skips_imageless(self, cursor):
        objects = [
            types.SimpleNamespace(object_id=224),
            types.SimpleNamespace(object_id=7000),
            types.SimpleNamespace(object_id=9),  # empty image_name
        ]
        assert set(
            store.worklist_for_scope(store.SCOPE_LIST, cursor, objects=objects)
        ) == {"NGC224", "NGC7000"}

    def test_empty_objects_returns_empty(self, cursor):
        assert store.worklist_for_scope(store.SCOPE_FILTER, cursor, objects=[]) == []

    def test_catalog_scope_requires_code(self, cursor):
        with pytest.raises(ValueError):
            store.worklist_for_scope(store.SCOPE_CATALOG, cursor)

    def test_unknown_scope_raises(self, cursor):
        with pytest.raises(ValueError):
            store.worklist_for_scope("bogus", cursor)


@pytest.mark.unit
class TestMissing:
    def test_missing_image_names(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "BASE_IMAGE_PATH", str(tmp_path))
        (tmp_path / "4").mkdir()
        (tmp_path / "4" / "NGC224.jpg").write_bytes(b"x")
        assert store.missing_image_names(["NGC224", "NGC7000"]) == ["NGC7000"]


class _FakeResponse:
    def __init__(self, status_code, content=b"jpegdata"):
        self.status_code = status_code
        self.content = content


class _FakeSession:
    def __init__(self, status_code):
        self._status_code = status_code
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return _FakeResponse(self._status_code)


@pytest.mark.unit
class TestDownloadObjectImage:
    def test_downloads_to_sourceless_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "BASE_IMAGE_PATH", str(tmp_path))
        result = store.download_object_image(_FakeSession(200), "NGC224")
        assert result == store.RESULT_DOWNLOADED
        assert (tmp_path / "4" / "NGC224.jpg").read_bytes() == b"jpegdata"

    def test_skips_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "BASE_IMAGE_PATH", str(tmp_path))
        (tmp_path / "4").mkdir()
        (tmp_path / "4" / "NGC224.jpg").write_bytes(b"old")
        session = _FakeSession(200)
        assert store.download_object_image(session, "NGC224") == store.RESULT_SKIPPED
        assert session.urls == []  # never hit the network
        assert (tmp_path / "4" / "NGC224.jpg").read_bytes() == b"old"

    def test_overwrite(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "BASE_IMAGE_PATH", str(tmp_path))
        (tmp_path / "4").mkdir()
        (tmp_path / "4" / "NGC224.jpg").write_bytes(b"old")
        result = store.download_object_image(
            _FakeSession(200), "NGC224", overwrite=True
        )
        assert result == store.RESULT_DOWNLOADED
        assert (tmp_path / "4" / "NGC224.jpg").read_bytes() == b"jpegdata"

    def test_404_is_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "BASE_IMAGE_PATH", str(tmp_path))
        assert (
            store.download_object_image(_FakeSession(404), "NGC7000")
            == store.RESULT_MISSING
        )
        assert not (tmp_path / "0" / "NGC7000.jpg").exists()
