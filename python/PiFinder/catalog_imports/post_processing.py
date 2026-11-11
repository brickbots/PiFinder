"""
Post-processing utilities for catalog data cleanup and fixes.

This module contains functions that run after catalog loading to fix
data issues and normalize object types across different catalogs.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# Import shared database object
from .database import objects_db
from .catalog_import_utils import NewCatalogObject
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.db.objects_db import ObjectsDatabase
import PiFinder.utils as utils


MESSIER_NAMES_FILE = Path(utils.astro_data_dir) / "ngc_ic_m/messier/messier_names.dat"

# Words a title leaves small after its first, as the Paper Chart atlas sets
# common names (paperChart, build/sources.py).
_SMALL = frozenset({"in", "of", "the", "and", "or", "a", "an"})


def title_case(name: str) -> str:
    """A common name in title case, by the atlas's rule: each word
    capitalised, and each part of a hyphenated one, but the small words
    after the first. A capital is never lowered: "Owl or E.T. Cluster"."""
    words = name.split(" ")
    return " ".join(
        w
        if i and w in _SMALL
        else "-".join(p[:1].upper() + p[1:] for p in w.split("-"))
        for i, w in enumerate(words)
    )


def parse_messier_names(lines: Iterable[str]) -> Dict[int, List[str]]:
    """
    Messier common names by M number, from the lines of messier_names.dat.

    Each line is ``M<n><TAB>Name; Name``, and its first name is that
    object's preferred name. The file is a curated source, so a line that
    doesn't parse fails the import rather than being skipped.
    """
    messier_names: Dict[int, List[str]] = {}
    for line_number, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        where = f"messier_names.dat line {line_number}"
        designation, tab, names_part = line.partition("\t")
        if not tab:
            raise ValueError(f"{where}: expected M<n><TAB>Name; Name, got {line!r}")
        if not designation.startswith("M") or not designation[1:].isdigit():
            raise ValueError(f"{where}: {designation!r} is not an M number")
        m_number = int(designation[1:])
        if m_number in messier_names:
            raise ValueError(f"{where}: M {m_number} is listed twice")
        names = [name.strip() for name in names_part.split(";") if name.strip()]
        if not names:
            raise ValueError(f"{where}: M {m_number} has no name")
        messier_names[m_number] = names

    return messier_names


def _load_messier_names(path: Path = MESSIER_NAMES_FILE) -> Dict[int, List[str]]:
    with open(path, "r", encoding="utf-8") as f:
        return parse_messier_names(f)


def put_names_first(
    cursor: sqlite3.Cursor, object_id: int, names: List[str], origin: str
) -> None:
    """
    Re-order one sky object's names so that `names` come first, in order.

    Names are ordered by row id, so putting some first means re-inserting
    them all. A name the sky object already has keeps its row (and origin);
    a new one is added with `origin`. The rest keep their order behind.
    """
    rows = [
        (row[0], row[1])
        for row in cursor.execute(
            "SELECT common_name, origin FROM names WHERE object_id = ? ORDER BY id",
            (object_id,),
        )
    ]
    first: List[Tuple[str, str]] = []
    for name in names:
        first += [row for row in rows if row[0] == name] or [(name, origin)]
    rest = [row for row in rows if row[0] not in names]
    cursor.execute("DELETE FROM names WHERE object_id = ?", (object_id,))
    cursor.executemany(
        "INSERT INTO names (object_id, common_name, origin) VALUES (?, ?, ?)",
        [(object_id, name, row_origin) for name, row_origin in first + rest],
    )


def add_messier_names(
    db: Optional[ObjectsDatabase] = None,
    messier_names: Optional[Dict[int, List[str]]] = None,
) -> None:
    """
    Put each Messier object's names from messier_names.dat ahead of its
    other names, so the first becomes its preferred name (catalog.md 9.6).

    Runs after add_missing_messier_objects, so every M listing exists.
    """
    logging.info("ADDING: Messier names")
    db = db or objects_db
    assert db is not None
    if messier_names is None:
        messier_names = _load_messier_names()

    for m_number, names in messier_names.items():
        listing = db.get_catalog_object_by_sequence("M", m_number)
        if listing is None:
            raise ValueError(
                f"messier_names.dat names M {m_number}, which no loader created"
            )
        put_names_first(db.cursor, listing["object_id"], names, "M")
    db.conn.commit()
    logging.info(f"ADDED: names for {len(messier_names)} Messier objects")


def fix_object_types():
    """
    Runs some global queries to normalize object types from various catalogs
    """
    logging.info("FIX: Object Types")
    conn, db_c = objects_db.get_conn_cursor()

    type_mappings = {
        "Dark Nebula": "DN",
        "* ": "*",
        "*?": "?",
        "-": "?",
        "": "?",
        "Bright Nebula": "Nb",
        "D*?": "D*",
        "Open Cluster": "OC",
        "Pl": "PN",
        "PD": "PN",
        "Supernova Remnant": "Nb",
    }

    for k, v in type_mappings.items():
        db_c.execute(f"update objects set obj_type = '{v}' where obj_type='{k}'")

    conn.commit()


def add_missing_messier_objects():
    """
    Add M24, M40, M45, and M102 which are missing from the main catalog loading
    """
    logging.info("ADDING: Missing Messier objects M24, M40, M45, and M102")

    # Their common names from messier_names.dat are placed by add_messier_names,
    # which runs next.

    # M40 - Winnecke 4 (Double star in Ursa Major)
    # RA: 12h 22m 12.5272s = 185.552°, Dec: +58° 4′ 58.549″ = +58.083°
    m40_aka_names = ["Winnecke 4", "WNC 4"]

    m40 = NewCatalogObject(
        object_type="D*",
        catalog_code="M",
        sequence=40,
        ra=185.552,  # 12h 22m 12.5272s in degrees
        dec=58.083,  # +58° 4′ 58.549″ in degrees
        mag=MagnitudeObject([9.9]),  # Average of components A (9.64) and B (10.11)
        size=SizeObject.from_arcmin(0.1),
        description="Winnecke 4 double star",
        aka_names=m40_aka_names,
    )
    m40.insert()

    # M45 - Pleiades (Open cluster in Taurus)
    # RA: 03h 47m 24s = 56.85°, Dec: +24° 07′ 00″ = +24.117°
    m45_aka_names = ["Cr 42", "Mel 22"]  # Keep catalog designations

    m45 = NewCatalogObject(
        object_type="OC",
        catalog_code="M",
        sequence=45,
        ra=56.85,  # 03h 47m 24s in degrees
        dec=24.117,  # +24° 07′ 00″ in degrees
        mag=MagnitudeObject([1.6]),
        size=SizeObject.from_degrees(2.0),  # 2°
        description="Pleiades open cluster",
        aka_names=m45_aka_names,
    )
    m45.insert()
    # "Cr 42" links M45 to the Collinder 42 object, which insert() does not
    # change. Set the Pleiades values above on that shared object.
    objects_db.update_object_by_id(
        m45.object_id,
        ra=m45.ra,
        dec=m45.dec,
        mag=m45.mag.to_json(),
        size=m45.size.to_json(),
    )

    # M24 - Sagittarius Star Cloud (no NGC equivalent, it's a dense star field)
    # RA: 18h 18m 24s = 274.6°, Dec: -18° 24′ 00″ = -18.4°
    # "IC 4715" links M24 to the IC 4715 object: Steinicke identifies it as M 24.
    m24_aka_names = ["Sagittarius Star Cloud", "IC 4715"]

    m24 = NewCatalogObject(
        object_type="Ast",  # Asterism/Star cloud
        catalog_code="M",
        sequence=24,
        ra=274.6,  # 18h 18m 24s in degrees
        dec=-18.4,  # -18° 24′ 00″ in degrees
        mag=MagnitudeObject([4.6]),  # Visual magnitude of the brightest part
        size=SizeObject.from_degrees(1.5),  # ~1.5°
        description="Sagittarius Star Cloud",
        aka_names=m24_aka_names,
    )
    m24.insert()

    # M102 - Usually identified with NGC 5866 (Spindle Galaxy)
    # RA: 15h 06m 29.5s = 226.623°, Dec: +55° 45′ 48″ = +55.763°
    m102_aka_names = ["NGC 5866", "Spindle Galaxy"]

    m102 = NewCatalogObject(
        object_type="Gx",  # Galaxy
        catalog_code="M",
        sequence=102,
        ra=226.623,  # 15h 06m 29.5s in degrees
        dec=55.763,  # +55° 45′ 48″ in degrees
        mag=MagnitudeObject([10.7]),
        size=SizeObject.from_arcmin(5.2, 2.3),
        description="Spindle Galaxy (controversial Messier object)",
        aka_names=m102_aka_names,
    )
    m102.insert()

    logging.info(
        "ADDED: M24 (Sagittarius Star Cloud), M40 (Winnecke 4), M45 (Pleiades), and M102 (NGC 5866)"
    )
