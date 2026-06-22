"""Tests for PiFinder.catalog_cache."""

import os
import pickle
import pytest

from PiFinder import catalog_cache
from PiFinder.composite_object import CompositeObject, MagnitudeObject


def _make_obj(seq: int, catalog_code: str = "NGC", logged: bool = False):
    obj = CompositeObject(
        id=seq,
        object_id=seq,
        ra=1.0 * seq,
        dec=-1.0 * seq,
        catalog_code=catalog_code,
        sequence=seq,
        description=f"obj {seq}",
        mag=MagnitudeObject([6.5]),
        logged=logged,
    )
    return obj


@pytest.fixture
def cache_paths(tmp_path, monkeypatch):
    """Redirect cache files into tmp_path and provide a fake source DB to fingerprint."""
    fake_db = tmp_path / "pifinder_objects.db"
    fake_db.write_bytes(b"\x00" * 128)

    pkl = tmp_path / "composite_objects.pkl"
    meta = tmp_path / "composite_objects.meta.json"

    monkeypatch.setattr(catalog_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(catalog_cache, "PICKLE_PATH", pkl)
    monkeypatch.setattr(catalog_cache, "META_PATH", meta)
    monkeypatch.setattr(catalog_cache, "pifinder_db", fake_db)

    return {"db": fake_db, "pkl": pkl, "meta": meta, "dir": tmp_path}


@pytest.mark.unit
def test_load_returns_none_when_no_cache(cache_paths):
    assert catalog_cache.load() is None


@pytest.mark.unit
def test_roundtrip_preserves_objects_and_info(cache_paths):
    objs = [_make_obj(i) for i in range(5)]
    info = {"NGC": {"desc": "ngc", "max_sequence": 100}}

    catalog_cache.save(objs, info)
    loaded = catalog_cache.load()

    assert loaded is not None
    out_objs, out_info = loaded
    assert len(out_objs) == 5
    assert out_info == info
    assert [o.sequence for o in out_objs] == [0, 1, 2, 3, 4]
    assert [o.catalog_code for o in out_objs] == ["NGC"] * 5


@pytest.mark.unit
def test_logged_is_not_persisted(cache_paths):
    """logged=True must be reset on save so user state doesn't leak across sessions."""
    objs = [_make_obj(i, logged=True) for i in range(3)]
    catalog_cache.save(objs, {})

    with cache_paths["pkl"].open("rb") as f:
        payload = pickle.load(f)

    assert all(o.logged is False for o in payload["composite_objects"])

    # And load() also returns logged=False
    loaded = catalog_cache.load()
    assert loaded is not None
    out_objs, _ = loaded
    assert all(o.logged is False for o in out_objs)


@pytest.mark.unit
def test_fingerprint_mismatch_invalidates(cache_paths):
    """If the source DB changes (mtime or size), the cache must be rejected."""
    objs = [_make_obj(0)]
    catalog_cache.save(objs, {})
    assert catalog_cache.load() is not None  # sanity

    # Bump the DB mtime and rewrite it to a new size — the cache should now be stale.
    cache_paths["db"].write_bytes(b"\x01" * 256)
    # Touch mtime to be safe even on fast filesystems.
    new_time = cache_paths["db"].stat().st_mtime + 10
    os.utime(cache_paths["db"], (new_time, new_time))

    assert catalog_cache.load() is None


@pytest.mark.unit
def test_corrupt_pickle_returns_none(cache_paths):
    catalog_cache.save([_make_obj(0)], {})
    # Sanity check first.
    assert catalog_cache.load() is not None

    # Corrupt the pickle without touching the meta file.
    cache_paths["pkl"].write_bytes(b"not a pickle")

    assert catalog_cache.load() is None


@pytest.mark.unit
def test_corrupt_meta_returns_none(cache_paths):
    catalog_cache.save([_make_obj(0)], {})
    cache_paths["meta"].write_text("not json{{")

    assert catalog_cache.load() is None


@pytest.mark.unit
def test_clear_removes_files(cache_paths):
    catalog_cache.save([_make_obj(0)], {})
    assert cache_paths["pkl"].exists() and cache_paths["meta"].exists()

    catalog_cache.clear()

    assert not cache_paths["pkl"].exists()
    assert not cache_paths["meta"].exists()

    # Calling clear when files are already gone must not raise.
    catalog_cache.clear()
