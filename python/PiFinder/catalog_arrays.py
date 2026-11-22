"""
Catalog listings as numpy columns: the builder, and the reader.

The DB catalogs (M, NGC, IC, WDS, ...) hold about 151,000 catalog listings.
As one ``CompositeObject`` each they used about 276 MB of RAM and took seconds
to load. This module turns the objects DB into one directory per catalog
with one ``.npy`` file per column and one UTF-8 blob per text field. The app
opens them with ``np.load(mmap_mode="r")``: that takes milliseconds, and the
pages come from the file cache, so they do not add to the process RAM.

Columns per catalog, one value per listing, sorted by sequence:

- ``id``, ``object_id``, ``sequence``: int32
- ``ra``, ``dec``, ``filter_mag``: float64
- ``obj_type``, ``const``: uint8 codes into the tables in ``meta.json``

Text, one blob per field with an int64 offset column (``<field>.off.npy``,
one more entry than listings): ``names`` (a listing's names joined by
``NAME_SEP``), ``description``, ``mag`` and ``size`` (the DB's JSON text),
``t9`` (the keypad digits of each name) and ``lower`` (the lower-case names).
Each listing's ``t9`` and ``lower`` text ends with ``NAME_SEP``, so a search
match never crosses two names.

The Nix build runs the builder in CI (``nixos/pkgs/catalog-arrays.nix``), so
a device never builds. Without Nix, ``locate`` builds into the cache
directory on the first start. Build by hand with::

    python -m PiFinder.catalog_arrays build [--db PATH] [--out DIR]
"""

import argparse
import json
import logging
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from PiFinder import utils
from PiFinder.composite_object import MagnitudeObject

logger = logging.getLogger("Catalog.Arrays")

# Change when the files change in a way the reader must know about.
FORMAT_VERSION = 1

META_FILE = "meta.json"
NAME_SEP = "\x1f"
TEXT_FIELDS = ("names", "description", "mag", "size", "t9", "lower")

# Arrays built in CI, linked into the source tree by the Nix build.
NIX_DIR = utils.pifinder_dir / "catalog_arrays"
# Arrays built on this machine, when the Nix arrays are missing or stale.
CACHE_DIR = utils.data_dir / "cache" / "catalog_arrays"
# The pickle cache that the arrays replace.
OLD_PICKLE_CACHE_DIR = utils.data_dir / "cache" / "catalogs"

# Keypad digit -> letters (the PiFinder keypad's own layout).
KEYPAD_DIGIT_TO_CHARS = {
    "7": "abc",
    "8": "def",
    "9": "ghi",
    "4": "jkl",
    "5": "mno",
    "6": "pqrs",
    "1": "tuv",
    "2": "wxyz",
    "3": "'-+/",
}

LETTER_TO_DIGIT_MAP: Dict[str, str] = {}
for _digit, _chars in KEYPAD_DIGIT_TO_CHARS.items():
    # Map the digit to itself so numbers in names still match
    LETTER_TO_DIGIT_MAP[_digit] = _digit
    for _char in _chars:
        LETTER_TO_DIGIT_MAP[_char] = _digit
        LETTER_TO_DIGIT_MAP[_char.upper()] = _digit

T9_TRANSLATOR = str.maketrans(LETTER_TO_DIGIT_MAP)
VALID_T9_DIGITS = "".join(KEYPAD_DIGIT_TO_CHARS.keys())
INVALID_T9_DIGITS_RE = re.compile(f"[^{VALID_T9_DIGITS}]")


def name_to_t9_digits(name: str) -> str:
    """The keypad digits that type ``name``; other characters are dropped."""
    return INVALID_T9_DIGITS_RE.sub("", name.translate(T9_TRANSLATOR))


# --- builder ----------------------------------------------------------------


def _db_stamp(db_path: Path) -> Dict[str, int]:
    """Size and modification time of the DB, to tell whether arrays match it."""
    stat = db_path.stat()
    return {"db_size": stat.st_size, "db_mtime_ns": stat.st_mtime_ns}


def _names_by_object_id(cursor) -> Dict[int, List[str]]:
    """object_id -> names, in DB order, stripped, without duplicates (the
    same rule as ObjectsDatabase.get_object_id_to_names)."""
    names = defaultdict(list)
    for object_id, name in cursor.execute(
        "SELECT object_id, common_name FROM names ORDER BY rowid"
    ):
        names[object_id].append(name.strip())
    return {oid: list(dict.fromkeys(values)) for oid, values in names.items()}


def _filter_mag(mag_json: str) -> float:
    try:
        return MagnitudeObject.from_json(mag_json).filter_mag
    except Exception:
        return MagnitudeObject.UNKNOWN_MAG


def _write_text(directory: Path, field: str, texts: List[str]) -> None:
    offsets = np.zeros(len(texts) + 1, dtype=np.int64)
    encoded = [text.encode("utf-8") for text in texts]
    offsets[1:] = np.cumsum([len(b) for b in encoded])
    with open(directory / f"{field}.bin", "wb") as f:
        for data in encoded:
            f.write(data)
    np.save(directory / f"{field}.off.npy", offsets)


def build(db_path: Path, out_dir: Path) -> None:
    """Builds the arrays for every catalog in the DB into ``out_dir``. The
    directory is replaced as a whole only when the build is complete."""
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".catalog_arrays.", dir=out_dir.parent))
    try:
        _build_into(db_path, work)
        old = out_dir.with_name(out_dir.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        if out_dir.exists():
            out_dir.rename(old)
        work.rename(out_dir)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _build_into(db_path: Path, out: Path) -> None:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cursor = connection.cursor()
        names_by_id = _names_by_object_id(cursor)
        objects = {
            row[0]: row[1:]
            for row in cursor.execute(
                "SELECT id, obj_type, ra, dec, const, size, mag FROM objects"
            )
        }
        catalogs = list(
            cursor.execute(
                "SELECT catalog_code, desc, max_sequence FROM catalogs ORDER BY rowid"
            )
        )
        listings = defaultdict(list)
        for row in cursor.execute(
            "SELECT id, object_id, catalog_code, sequence, description"
            " FROM catalog_objects"
        ):
            listings[row[2]].append(row)
    finally:
        connection.close()

    obj_types: Dict[str, int] = {}
    consts: Dict[str, int] = {}
    catalog_meta = []
    for code, desc, max_sequence in catalogs:
        rows = sorted(listings.get(code, []), key=lambda r: r[3])
        directory = out / code
        directory.mkdir()
        n = len(rows)
        ids = np.empty(n, dtype=np.int32)
        object_ids = np.empty(n, dtype=np.int32)
        sequences = np.empty(n, dtype=np.int32)
        ra = np.empty(n, dtype=np.float64)
        dec = np.empty(n, dtype=np.float64)
        filter_mag = np.empty(n, dtype=np.float64)
        type_codes = np.empty(n, dtype=np.uint8)
        const_codes = np.empty(n, dtype=np.uint8)
        texts: Dict[str, List[str]] = {field: [] for field in TEXT_FIELDS}
        for i, (listing_id, object_id, _code, sequence, description) in enumerate(rows):
            obj_type, obj_ra, obj_dec, const, size, mag = objects[object_id]
            names = names_by_id.get(object_id, [])
            ids[i] = listing_id
            object_ids[i] = object_id
            sequences[i] = sequence
            ra[i] = obj_ra
            dec[i] = obj_dec
            filter_mag[i] = _filter_mag(mag or "")
            type_codes[i] = obj_types.setdefault(obj_type or "", len(obj_types))
            const_codes[i] = consts.setdefault(const or "", len(consts))
            texts["names"].append(NAME_SEP.join(names))
            texts["description"].append(description or "")
            texts["mag"].append(mag or "")
            texts["size"].append(size or "")
            texts["t9"].append(
                "".join(name_to_t9_digits(name) + NAME_SEP for name in names)
            )
            texts["lower"].append("".join(name.lower() + NAME_SEP for name in names))
        if len(obj_types) > 255 or len(consts) > 255:
            raise ValueError("more than 255 object types or constellations")
        for name, values in (
            ("id", ids),
            ("object_id", object_ids),
            ("sequence", sequences),
            ("ra", ra),
            ("dec", dec),
            ("filter_mag", filter_mag),
            ("obj_type", type_codes),
            ("const", const_codes),
        ):
            np.save(directory / f"{name}.npy", values)
        for field in TEXT_FIELDS:
            _write_text(directory, field, texts[field])
        catalog_meta.append(
            {"code": code, "desc": desc, "max_sequence": max_sequence, "rows": n}
        )

    meta = {
        "format": FORMAT_VERSION,
        **_db_stamp(db_path),
        "obj_types": list(obj_types),
        "consts": list(consts),
        "catalogs": catalog_meta,
    }
    with open(out / META_FILE, "w") as f:
        json.dump(meta, f, indent=1)
    logger.info(
        "Built catalog arrays: %d catalogs, %d listings",
        len(catalog_meta),
        sum(c["rows"] for c in catalog_meta),
    )


# --- reader -----------------------------------------------------------------


def _read_meta(directory: Path) -> Optional[dict]:
    try:
        with open(directory / META_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _matches(directory: Path, db_path: Path) -> bool:
    meta = _read_meta(directory)
    if meta is None or meta.get("format") != FORMAT_VERSION:
        return False
    stamp = _db_stamp(db_path)
    return all(meta.get(key) == value for key, value in stamp.items())


def locate(db_path: Path = utils.pifinder_db) -> Path:
    """
    The directory with arrays that match ``db_path``: the arrays from the
    Nix build, else the cache directory, built now when it is missing or
    stale.
    """
    if _matches(NIX_DIR, db_path):
        return NIX_DIR
    if NIX_DIR.exists():
        logger.error(
            "Catalog arrays in %s do not match %s; building a copy", NIX_DIR, db_path
        )
    if not _matches(CACHE_DIR, db_path):
        logger.info("Building catalog arrays into %s", CACHE_DIR)
        build(db_path, CACHE_DIR)
    return CACHE_DIR


def remove_old_pickle_cache() -> None:
    """Deletes the pickle cache that older versions wrote (about 47 MB)."""
    if OLD_PICKLE_CACHE_DIR.exists():
        shutil.rmtree(OLD_PICKLE_CACHE_DIR, ignore_errors=True)
        logger.info("Removed the old catalog pickle cache %s", OLD_PICKLE_CACHE_DIR)


class CatalogColumns:
    """The read-only columns of one catalog, memory-mapped."""

    def __init__(self, directory: Path, meta: dict, catalog_meta: dict):
        self.catalog_code: str = catalog_meta["code"]
        self.desc: str = catalog_meta["desc"]
        self.max_sequence: int = catalog_meta["max_sequence"]
        path = directory / self.catalog_code
        self.id = np.load(path / "id.npy", mmap_mode="r")
        self.object_id = np.load(path / "object_id.npy", mmap_mode="r")
        self.sequence = np.load(path / "sequence.npy", mmap_mode="r")
        self.ra = np.load(path / "ra.npy", mmap_mode="r")
        self.dec = np.load(path / "dec.npy", mmap_mode="r")
        self.filter_mag = np.load(path / "filter_mag.npy", mmap_mode="r")
        self.obj_type_codes = np.load(path / "obj_type.npy", mmap_mode="r")
        self.const_codes = np.load(path / "const.npy", mmap_mode="r")
        self.obj_type_table = np.array(meta["obj_types"], dtype=str)
        self.const_table = np.array(meta["consts"], dtype=str)
        self._text = {}
        for field in TEXT_FIELDS:
            offsets = np.load(path / f"{field}.off.npy", mmap_mode="r")
            blob_path = path / f"{field}.bin"
            blob = (
                np.memmap(blob_path, dtype=np.uint8, mode="r")
                if blob_path.stat().st_size
                else np.zeros(0, dtype=np.uint8)
            )
            self._text[field] = (blob, offsets)

    def __len__(self) -> int:
        return len(self.sequence)

    def text(self, field: str, row: int) -> str:
        blob, offsets = self._text[field]
        return bytes(blob[offsets[row] : offsets[row + 1]]).decode("utf-8")

    def names(self, row: int) -> List[str]:
        text = self.text("names", row)
        return text.split(NAME_SEP) if text else []

    def obj_type(self) -> np.ndarray:
        return self.obj_type_table[self.obj_type_codes]

    def const(self) -> np.ndarray:
        return self.const_table[self.const_codes]

    def search(self, field: str, pattern: str) -> np.ndarray:
        """Rows whose ``field`` text ("t9" or "lower") contains ``pattern``."""
        if not pattern:
            return np.zeros(0, dtype=np.int64)
        blob, offsets = self._text[field]
        positions = find_all(blob, pattern.encode("utf-8"))
        if not len(positions):
            return np.zeros(0, dtype=np.int64)
        rows = np.searchsorted(offsets, positions, side="right") - 1
        return np.unique(rows)


def find_all(blob: np.ndarray, pattern: bytes) -> np.ndarray:
    """Start positions of every occurrence of ``pattern`` in ``blob``."""
    length = len(pattern)
    if length == 0 or length > len(blob):
        return np.zeros(0, dtype=np.int64)
    last = len(blob) - length
    candidates = np.flatnonzero(blob[: last + 1] == pattern[0])
    for offset in range(1, length):
        if not len(candidates):
            break
        candidates = candidates[blob[candidates + offset] == pattern[offset]]
    return candidates


def open_catalogs(directory) -> List[CatalogColumns]:
    """The columns of every catalog in ``directory``, in DB order."""
    directory = Path(directory)
    meta = _read_meta(directory)
    if meta is None:
        raise FileNotFoundError(f"no catalog arrays in {directory}")
    return [CatalogColumns(directory, meta, c) for c in meta["catalogs"]]


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build", help="build the arrays from the DB")
    build_parser.add_argument("--db", type=Path, default=utils.pifinder_db)
    build_parser.add_argument("--out", type=Path, default=CACHE_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    if args.command == "build":
        build(args.db, args.out)


if __name__ == "__main__":
    main(sys.argv[1:])
