"""
Tests for the DB catalogs as numpy columns (PiFinder/catalog_arrays.py) and
the ArrayCatalog that serves them (PiFinder/catalogs.py).

The main check builds the arrays from the real objects DB and compares every
catalog listing that ArrayCatalog makes with the CompositeObject that the
earlier per-object builder made from the same DB rows (``_reference_objects``
keeps those rules). Search, filter and logged state are compared with the
per-object algorithms in the same way.
"""

import datetime
import sqlite3
from collections import defaultdict
from types import SimpleNamespace

import numpy as np
import pytest

from PiFinder import catalog_arrays, utils
from PiFinder.catalog_arrays import name_to_t9_digits
from PiFinder.catalogs import ArrayCatalog, CatalogBuilder, CatalogFilter, Catalogs
from PiFinder.composite_object import CompositeObject, MagnitudeObject, SizeObject
from PiFinder.nearby import deduplicate_objects
from PiFinder.object_sequence import ObjectSequence
from PiFinder.state import Location

pytestmark = pytest.mark.unit


# --- the per-object rules the arrays replace --------------------------------


def _reference_objects(db_path):
    """{catalog_code: [CompositeObject]} built row by row, as the builder
    before the arrays did it (names, magnitude, size, description)."""
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    names = defaultdict(list)
    for object_id, name in cursor.execute(
        "SELECT object_id, common_name FROM names ORDER BY rowid"
    ):
        names[object_id].append(name.strip())
    names = {oid: list(dict.fromkeys(values)) for oid, values in names.items()}
    objects = {
        row[0]: row[1:]
        for row in cursor.execute(
            "SELECT id, obj_type, ra, dec, const, size, mag FROM objects"
        )
    }
    result = defaultdict(list)
    for listing_id, object_id, code, sequence, description in cursor.execute(
        "SELECT id, object_id, catalog_code, sequence, description"
        " FROM catalog_objects"
    ):
        obj_type, ra, dec, const, size, mag = objects[object_id]
        obj = CompositeObject(
            id=listing_id,
            object_id=object_id,
            obj_type=obj_type,
            ra=ra,
            dec=dec,
            const=const,
            catalog_code=code,
            sequence=sequence,
            description=description,
            names=names.get(object_id, []),
        )
        try:
            obj.mag = MagnitudeObject.from_json(mag)
            obj.mag_str = obj.mag.calc_two_mag_representation()
        except Exception:
            obj.mag = MagnitudeObject([])
            obj.mag_str = "-"
        obj.size = SizeObject.from_json(size)
        result[code].append(obj)
    connection.close()
    for code in result:
        result[code].sort(key=lambda o: o.sequence)
    return result


def _fields(obj):
    return (
        obj.id,
        obj.object_id,
        obj.obj_type,
        float(obj.ra),
        float(obj.dec),
        obj.const,
        obj.catalog_code,
        obj.sequence,
        obj.description,
        obj.names,
        obj.mag.mags,
        obj.mag.filter_mag,
        obj.mag_str,
        obj.size.extents,
        obj.size.position_angle,
    )


# --- fixtures ---------------------------------------------------------------


@pytest.fixture(scope="module")
def real_arrays(tmp_path_factory):
    directory = tmp_path_factory.mktemp("arrays") / "catalog_arrays"
    catalog_arrays.build(utils.pifinder_db, directory)
    return directory


@pytest.fixture(scope="module")
def reference():
    return _reference_objects(utils.pifinder_db)


def _catalogs(directory, logged=None):
    catalogs = [
        ArrayCatalog(
            columns,
            np.zeros(len(columns), dtype=bool) if logged is None else logged(columns),
        )
        for columns in catalog_arrays.open_catalogs(directory)
    ]
    return Catalogs(catalogs)


class _State:
    """Read side of the shared state for the filter, with an alt/az fix."""

    def location(self):
        return Location(lat=51.2, lon=4.4, lock=True)

    def datetime(self):
        return datetime.datetime(2026, 9, 30, 21, 0, tzinfo=datetime.timezone.utc)

    def altaz_ready(self):
        return True


# --- builder ----------------------------------------------------------------


def _small_db(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE objects (id INTEGER PRIMARY KEY, obj_type TEXT, ra NUMERIC,
            dec NUMERIC, const TEXT, size TEXT, mag TEXT, surface_brightness NUMERIC);
        CREATE TABLE names (id INTEGER PRIMARY KEY, object_id INTEGER,
            common_name TEXT, origin TEXT);
        CREATE TABLE catalogs (catalog_code TEXT PRIMARY KEY, max_sequence INT,
            desc TEXT);
        CREATE TABLE catalog_objects (id INTEGER PRIMARY KEY, object_id INTEGER,
            catalog_code TEXT, sequence INTEGER, description TEXT);
        INSERT INTO objects VALUES
            (1, 'Gx', 10, 41.3, 'And', '{"e": [11400, 3600], "p": 35}',
             '{"mags": [3.4]}', NULL),
            (2, 'PN', 283.4, 33.0, 'Lyr', '', '{"mags": ["x"]}', NULL),
            (3, 'D*', 1.5, -2.25, 'Psc', 'legacy', 'legacy', NULL);
        INSERT INTO names (object_id, common_name) VALUES
            (1, 'Andromeda Galaxy '), (1, 'M 31'), (1, 'Andromeda Galaxy'),
            (2, 'Ring Nébula');
        INSERT INTO catalogs VALUES ('M', 110, 'Messier'), ('X', 5, 'Test');
        INSERT INTO catalog_objects VALUES
            (10, 2, 'M', 57, 'ring'), (11, 1, 'M', 31, 'big'),
            (12, 1, 'X', 2, ''), (13, 3, 'X', 5, 'no names');
        """
    )
    connection.commit()
    connection.close()


def test_the_builder_writes_sorted_columns_and_text(tmp_path):
    db = tmp_path / "objects.db"
    _small_db(db)
    out = tmp_path / "arrays"
    catalog_arrays.build(db, out)
    columns = {c.catalog_code: c for c in catalog_arrays.open_catalogs(out)}

    m = columns["M"]
    assert m.desc == "Messier" and m.max_sequence == 110
    assert list(m.sequence) == [31, 57]
    assert list(m.object_id) == [1, 2]
    assert m.ra[0] == 10.0
    assert m.names(0) == ["Andromeda Galaxy", "M 31"]
    assert m.names(1) == ["Ring Nébula"]
    assert m.text("description", 1) == "ring"
    assert m.filter_mag[0] == 3.4
    assert m.filter_mag[1] == MagnitudeObject.UNKNOWN_MAG
    assert list(m.obj_type()) == ["Gx", "PN"]

    x = columns["X"]
    assert x.names(1) == []
    assert x.text("description", 0) == ""


def test_search_finds_names_and_never_across_two_names(tmp_path):
    db = tmp_path / "objects.db"
    _small_db(db)
    catalog_arrays.build(db, tmp_path / "arrays")
    m = catalog_arrays.open_catalogs(tmp_path / "arrays")[0]
    assert list(m.search("lower", "nébula")) == [1]
    assert list(m.search("lower", "galaxy")) == [0]
    # "galaxy" + "m 31" must not match across the name boundary.
    assert list(m.search("lower", "galaxym")) == []
    assert list(m.search("t9", name_to_t9_digits("M 31"))) == [0]
    assert list(m.search("t9", "")) == []


def test_locate_builds_the_cache_when_the_nix_arrays_are_missing(tmp_path, monkeypatch):
    db = tmp_path / "objects.db"
    _small_db(db)
    monkeypatch.setattr(catalog_arrays, "NIX_DIR", tmp_path / "nix")
    monkeypatch.setattr(catalog_arrays, "CACHE_DIR", tmp_path / "cache")
    assert catalog_arrays.locate(db) == tmp_path / "cache"
    assert (tmp_path / "cache" / "meta.json").exists()

    # Arrays that match the DB are used as they are.
    catalog_arrays.build(db, tmp_path / "nix")
    assert catalog_arrays.locate(db) == tmp_path / "nix"


def test_locate_builds_again_when_the_db_changes(tmp_path, monkeypatch):
    db = tmp_path / "objects.db"
    _small_db(db)
    monkeypatch.setattr(catalog_arrays, "NIX_DIR", tmp_path / "nix")
    monkeypatch.setattr(catalog_arrays, "CACHE_DIR", tmp_path / "cache")
    catalog_arrays.locate(db)
    connection = sqlite3.connect(db)
    connection.execute("INSERT INTO catalog_objects VALUES (14, 2, 'X', 3, 'new')")
    connection.commit()
    connection.close()
    directory = catalog_arrays.locate(db)
    x = catalog_arrays.open_catalogs(directory)[1]
    assert list(x.sequence) == [2, 3, 5]


# --- the real DB ------------------------------------------------------------


def test_every_listing_matches_the_per_object_builder(real_arrays, reference):
    catalogs = _catalogs(real_arrays)
    codes = catalogs.get_codes(only_selected=False)
    assert set(codes) == set(reference)
    for catalog in catalogs.get_catalogs(only_selected=False):
        expected = reference[catalog.catalog_code]
        assert catalog.get_count() == len(expected)
        for i, obj in enumerate(expected):
            assert _fields(catalog._make_row(i)) == _fields(obj), (
                catalog.catalog_code,
                obj.sequence,
            )


def test_rows_by_sequence_and_the_row_cache(real_arrays):
    catalogs = _catalogs(real_arrays)
    m31 = catalogs.get_object("M", 31)
    assert m31.names[0] and m31.sequence == 31
    assert catalogs.get_object("M", 31) is m31
    assert catalogs.get_object("M", 9999) is None
    ngc = catalogs.get_catalog_by_code("NGC")
    assert ngc.get_object_by_id(ngc.get_objects()[5].id).sequence == 6


@pytest.mark.parametrize("digits", ["531", "5", "26374", "7263", "88587"])
def test_t9_search_matches_the_per_object_search(real_arrays, reference, digits):
    found = _catalogs(real_arrays).search_by_t9(digits)
    expected = [
        (obj.catalog_code, obj.sequence)
        for objects in reference.values()
        for obj in objects
        if any(digits in name_to_t9_digits(name) for name in obj.names)
    ]
    got = list(zip(found.column("catalog_code"), found.column("sequence")))
    assert sorted(got) == sorted(expected)


@pytest.mark.parametrize("text", ["Andromeda", "ngc 70", "Ring", "é", "zzqx"])
def test_text_search_matches_the_per_object_search(real_arrays, reference, text):
    found = _catalogs(real_arrays).search_by_text(text)
    expected = [
        (obj.catalog_code, obj.sequence)
        for objects in reference.values()
        for obj in objects
        if any(text.lower() in name.lower() for name in obj.names)
    ]
    got = list(zip(found.column("catalog_code"), found.column("sequence")))
    assert sorted(got) == sorted(expected)


@pytest.mark.parametrize(
    "criteria",
    [
        {"altitude": 20},
        {"magnitude": 9.0, "object_types": ["Gx", "OC"]},
        {"constellations": ["Cyg", "And"], "altitude": 0},
    ],
)
def test_the_filter_on_columns_matches_the_filter_on_objects(
    real_arrays, reference, criteria
):
    catalogs = _catalogs(real_arrays)
    catalogs.set_catalog_filter(CatalogFilter(shared_state=_State(), **criteria))
    catalogs.filter_catalogs()
    reference_filter = CatalogFilter(shared_state=_State(), **criteria)
    for catalog in catalogs.get_catalogs(only_selected=False):
        passed = reference_filter.apply(list(reference[catalog.catalog_code]))
        assert list(catalog.get_filtered_objects().column("sequence")) == [
            obj.sequence for obj in passed
        ], catalog.catalog_code


def test_the_row_carries_its_filter_verdict(real_arrays):
    catalogs = _catalogs(real_arrays)
    catalogs.set_catalog_filter(CatalogFilter(shared_state=_State(), magnitude=5.0))
    catalogs.filter_catalogs()
    messier = catalogs.get_catalog_by_code("M")
    bright = messier.get_filtered_objects()[0]
    assert bright.last_filtered_result is True
    faint_row = int(np.flatnonzero(~messier.verdict)[0])
    assert messier.row(faint_row).last_filtered_result is False


def test_logged_state_comes_from_the_observations(real_arrays):
    columns = {c.catalog_code: c for c in catalog_arrays.open_catalogs(real_arrays)}
    messier = columns["M"]
    m31_object_id = int(messier.object_id[np.searchsorted(messier.sequence, 31)])
    obs_db = SimpleNamespace(
        observed_object_ids={m31_object_id},
        observed_objects_cache={("NGC", 7000)},
    )
    logged = {code: CatalogBuilder._logged(c, obs_db) for code, c in columns.items()}
    catalogs = _catalogs(real_arrays, logged=lambda c: logged[c.catalog_code])
    assert catalogs.get_object("M", 31).logged
    assert catalogs.get_object("NGC", 224).logged  # the same sky object
    assert catalogs.get_object("NGC", 7000).logged  # the listing itself
    assert not catalogs.get_object("M", 1).logged


def test_mark_logged_marks_every_listing_of_the_sky_object(real_arrays):
    catalogs = _catalogs(real_arrays)
    catalogs.set_catalog_filter(CatalogFilter(shared_state=_State()))
    ngc224 = catalogs.get_object("NGC", 224)
    assert not ngc224.logged
    catalogs.mark_logged(catalogs.get_object("M", 31))
    assert ngc224.logged  # the cached row changes too
    ngc = catalogs.get_catalog_by_code("NGC")
    row = int(np.searchsorted(ngc.columns.sequence, 224))
    assert ngc.logged[row]


def test_all_filtered_and_nearby_dedup_need_no_object(real_arrays, reference):
    catalogs = _catalogs(real_arrays)
    catalogs.set_catalog_filter(CatalogFilter(shared_state=_State()))
    catalogs.filter_catalogs()
    everything = catalogs.get_objects(only_selected=False, filtered=True)
    assert len(everything) == sum(len(v) for v in reference.values())
    deduplicated = deduplicate_objects(everything)
    assert len(deduplicated) == len(set(everything.column("object_id")))
    # M 31 wins over NGC 224 for the same sky object.
    kept = set(
        zip(deduplicated.column("catalog_code"), deduplicated.column("sequence"))
    )
    assert ("M", 31) in kept and ("NGC", 224) not in kept
    for catalog in catalogs.get_catalogs(only_selected=False):
        assert len(catalog._rows) == 0, catalog.catalog_code


# --- ObjectSequence ---------------------------------------------------------


def _obj(seq, object_id, code="TST", ra=0.0):
    return CompositeObject(
        object_id=object_id, sequence=seq, catalog_code=code, ra=ra, dec=0.0
    )


def test_an_object_sequence_reads_like_a_list():
    objects = [_obj(1, 10, ra=30.0), _obj(2, 20, ra=10.0), _obj(3, 30, ra=20.0)]
    seq = ObjectSequence.from_objects(objects)
    assert len(seq) == 3
    assert seq[0] is objects[0] and seq[-1] is objects[2]
    assert list(seq[1:]) == objects[1:]
    assert seq.index(_obj(99, 20)) == 1  # equality is on object_id
    assert _obj(0, 30) in seq and _obj(0, 31) not in seq
    assert seq == objects and seq != objects[:2]
    by_ra = seq.take(np.argsort(seq.column("ra"), kind="stable"))
    assert [o.sequence for o in by_ra] == [2, 3, 1]
    assert [o.sequence for o in seq.mask(np.array([True, False, True]))] == [1, 3]
    with pytest.raises(IndexError):
        seq[3]
    with pytest.raises(ValueError):
        seq.index(_obj(0, 99))


def test_concat_keeps_order_and_mixes_sources(real_arrays):
    catalogs = _catalogs(real_arrays)
    messier = catalogs.get_catalog_by_code("M")
    planets = ObjectSequence.from_objects([_obj(1, -5, code="PL")])
    both = ObjectSequence.concat([messier.get_objects()[:2], planets])
    assert len(both) == 3
    assert list(both.column("catalog_code")) == ["M", "M", "PL"]
    assert list(both.column("sequence")) == [1, 2, 1]
    assert both[2].catalog_code == "PL"
    assert len(ObjectSequence.concat([])) == 0
