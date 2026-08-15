"""
Perek-Kohoutek galactic planetary nebula catalog load script.

Sources (vendored under astro_data/perek_kohoutek/, see PROVENANCE.md there):
    IV/24  - Catalogue of Galactic Planetary Nebulae, Kohoutek 2001
             https://cdsarc.cds.unistra.fr/ftp/IV/24/
             table2 supplies the 1510 rows; table4 supplies arcsecond positions.
    V/84   - Strasbourg-ESO Catalogue of Galactic Planetary Nebulae,
             Acker et al. 1992, https://cdsarc.cds.unistra.fr/ftp/V/84/
             main supplies cross-identifications, diam supplies sizes.
    SIMBAD - positions and cross-identifications keyed on PK designations.

Every position used here is J2000: SIMBAD is ICRS, and both IV/24 tables carry
author-computed J2000 columns alongside their B1950 originals. The B1950
columns are never read, so no precession happens in this loader.

Design notes live in docs/adr/0024-perek-kohoutek-catalog.md.
"""

import csv
import logging
import math
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

from tqdm import tqdm

import PiFinder.utils as utils
from PiFinder.composite_object import MagnitudeObject, SizeObject
from .catalog_import_utils import (
    ObjectFinder,
    NewCatalogObject,
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
    parse_designation,
    trim_string,
)

# Import shared database object
from .database import objects_db

CATALOG_CODE = "PK"
OBJECT_TYPE = "PN"

DATA_DIR = Path(utils.astro_data_dir, "perek_kohoutek")

# SIMBAD spells otype "PN" for a confirmed planetary nebula. Its position is
# preferred for those; for anything else (SIMBAD disagreeing with Kohoutek's
# classification) the catalogue's own position is kept.
SIMBAD_PN_OTYPES = {"PN", "PN?"}

# A refined position is only accepted when it agrees with the catalogue's own
# coarse position. table2 rounds to 0.1 minute of right ascension and 1
# arcminute of declination, so honest disagreement stays under ~2 arcminutes.
# Anything beyond this means a typo in the source or a SIMBAD identifier
# resolving to the wrong object — IV/24 table4 carries at least one, an
# equinox-2000 row for Vy 1-4 reading -02 26 where its five sibling rows and
# SIMBAD all read -06 26.
POSITION_AGREEMENT_ARCMIN = 5.0


class Position(NamedTuple):
    ra: float
    dec: float
    source: str


def _hms_to_deg(hours: float, minutes: float, seconds: float = 0.0) -> float:
    return (hours + minutes / 60.0 + seconds / 3600.0) * 15.0


def _dms_to_deg(sign: str, degrees: float, minutes: float, secs: float = 0.0) -> float:
    magnitude = degrees + minutes / 60.0 + secs / 3600.0
    return -magnitude if sign.strip() == "-" else magnitude


def _field(line: str, start: int, end: int) -> str:
    """One fixed-width field, using the ReadMe's 1-based inclusive byte range."""
    return line[start - 1 : end].strip()


def _pk_key(raw: str) -> Optional[str]:
    """Canonical join key for a PK designation.

    Each source spells it differently — "036+17.1" in IV/24, "036+17  1" in
    SIMBAD, "171-25 1" in V/84 — so reduce them all to "036+17.1".
    """
    text = trim_string(raw)
    if text.upper().startswith("PK "):
        text = text[3:].strip()
    if len(text) < 6:
        return None
    longitude, latitude = text[:3], text[3:6]
    if not longitude.isdigit() or latitude[0] not in "+-" or not latitude[1:].isdigit():
        return None
    running = text[6:].strip(" .")
    if not running.isdigit():
        return None
    return f"{longitude}{latitude}.{int(running)}"


def _pk_display_names(key: str) -> List[str]:
    """Both spellings of a PK designation, so either one is searchable."""
    longitude_latitude, running = key.split(".")
    return [f"PK {longitude_latitude}.{running}", f"PK {longitude_latitude} {running}"]


def _designation_aliases(raw: str) -> Tuple[List[str], List[str]]:
    """Split one source designation into linking aliases and plain names.

    The first list holds canonical "<code> <sequence>" forms that
    ObjectFinder can resolve to an existing sky object. The second holds the
    designation as the source wrote it, for search. A hyphenated NGC pair like
    "NGC 650-1" (M76) names two catalog entries and yields both.
    """
    name = trim_string(raw)
    if not name:
        return [], []

    linking: List[str] = []
    parsed = parse_designation(name)
    if parsed is not None:
        catalog_code, sequence = parsed
        linking.append(f"{catalog_code} {sequence}")
    elif name.upper().startswith("NGC "):
        linking.extend(_ngc_pair(name[4:]))

    return linking, [name]


def _ngc_pair(raw: str) -> List[str]:
    """Expand a hyphenated NGC pair, e.g. "650-1" -> NGC 650 and NGC 651.

    The digits after the hyphen replace the tail of the first number, so
    "650-1" means 650 and 651, not 650 and 1.
    """
    halves = [half.strip() for half in raw.split("-")]
    if len(halves) != 2 or not all(half.isdigit() for half in halves):
        return []
    first, tail = halves
    if len(tail) > len(first):
        return []
    second = first[: len(first) - len(tail)] + tail
    return [f"NGC {int(first)}", f"NGC {int(second)}"]


def _read_table2() -> List[Dict[str, str]]:
    """IV/24/table2 — the authoritative 1510 rows, ordered by right ascension."""
    rows = []
    with open(DATA_DIR / "table2.dat", "r") as table2:
        for line in table2:
            if not line.strip():
                continue
            rows.append(
                {
                    "pk": _field(line, 1, 9),
                    "f_pk": _field(line, 10, 10),
                    "name": _field(line, 12, 25),
                    "ra_h": _field(line, 50, 51),
                    "ra_m": _field(line, 53, 56),
                    "de_sign": _field(line, 59, 59) or "+",
                    "de_d": _field(line, 60, 61),
                    "de_m": _field(line, 63, 64),
                    "png": _field(line, 68, 78),
                    "note": _field(line, 80, 80),
                }
            )
    return rows


def angular_separation_arcmin(first: Position, second: Position) -> float:
    """Great-circle separation between two positions, in arcminutes."""
    ra1, dec1 = math.radians(first.ra), math.radians(first.dec)
    ra2, dec2 = math.radians(second.ra), math.radians(second.dec)
    cosine = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(
        dec2
    ) * math.cos(ra1 - ra2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine)))) * 60.0


def _read_table4() -> Dict[str, List[Position]]:
    """IV/24/table4 — arcsecond J2000 positions, several rows per nebula.

    The J2000 columns are author-computed from the row's own equinox, so any
    row is usable. Rows already given at equinox 2000 are listed first,
    because they needed no conversion; the caller takes the first one that
    agrees with the catalogue's own coarse position.
    """
    ranked: Dict[str, List[Tuple[int, Position]]] = {}
    with open(DATA_DIR / "table4.dat", "r") as table4:
        for line in table4:
            key = _pk_key(_field(line, 1, 9))
            if key is None:
                continue
            ra_h, ra_m, ra_s = (
                _field(line, 82, 83),
                _field(line, 85, 86),
                _field(line, 88, 92),
            )
            de_d, de_m, de_s = (
                _field(line, 95, 96),
                _field(line, 98, 99),
                _field(line, 101, 104),
            )
            if not (ra_h and ra_m and de_d and de_m):
                continue
            try:
                position = Position(
                    _hms_to_deg(float(ra_h), float(ra_m), float(ra_s or 0)),
                    _dms_to_deg(
                        _field(line, 94, 94) or "+",
                        float(de_d),
                        float(de_m),
                        float(de_s or 0),
                    ),
                    "IV/24 table4",
                )
            except ValueError:
                continue
            equinox = _field(line, 55, 58)
            ranked.setdefault(key, []).append((0 if equinox == "2000" else 1, position))
    return {
        key: [position for _rank, position in sorted(rows, key=lambda row: row[0])]
        for key, rows in ranked.items()
    }


def _read_v84_main() -> Dict[str, Dict[str, str]]:
    """V/84/main, keyed on the PN G designation shared with IV/24."""
    entries = {}
    with open(DATA_DIR / "main.dat", "r") as main:
        for line in main:
            png = _field(line, 1, 10)
            if not png:
                continue
            entries[png] = {
                "name": _field(line, 46, 58),
                "iras": _field(line, 70, 80),
                "idents": _field(line, 115, 224),
            }
    return entries


def _read_v84_diam() -> Dict[str, SizeObject]:
    """V/84/diam — optical diameter preferred, radio diameter as fallback."""
    sizes = {}
    with open(DATA_DIR / "diam.dat", "r") as diam:
        for line in diam:
            png = _field(line, 1, 10)
            if not png:
                continue
            for start, end in ((14, 19), (52, 57)):
                try:
                    arcsec = float(_field(line, start, end))
                except ValueError:
                    continue
                if arcsec > 0:
                    sizes[png] = SizeObject.from_arcsec(arcsec)
                    break
    return sizes


def _read_simbad_positions() -> Dict[str, Position]:
    """SIMBAD ICRS positions, keyed on the PK identifier."""
    positions = {}
    with open(DATA_DIR / "simbad_pk.tsv", "r") as simbad:
        for row in csv.DictReader(simbad, delimiter="\t"):
            key = _pk_key(row["id"].strip('"'))
            if key is None or row["otype"].strip('"') not in SIMBAD_PN_OTYPES:
                continue
            try:
                positions[key] = Position(float(row["ra"]), float(row["dec"]), "SIMBAD")
            except (TypeError, ValueError):
                continue
    return positions


def _read_simbad_aliases() -> Dict[str, List[str]]:
    """SIMBAD cross-identifications, keyed on the PK identifier."""
    aliases: Dict[str, List[str]] = {}
    with open(DATA_DIR / "simbad_pk_aliases.tsv", "r") as simbad:
        for row in csv.DictReader(simbad, delimiter="\t"):
            key = _pk_key(row["pk_id"].strip('"'))
            if key is None:
                continue
            alias = trim_string(row["alias"].strip('"'))
            if alias and alias not in aliases.setdefault(key, []):
                aliases[key].append(alias)
    return aliases


def _choose_position(candidates: List[Position], anchor: Position) -> Position:
    """First candidate that agrees with the catalogue's own coarse position.

    Falls back to the anchor when every refined candidate disagrees, so a bad
    source row can only cost precision, never correctness.
    """
    for candidate in candidates:
        if angular_separation_arcmin(candidate, anchor) <= POSITION_AGREEMENT_ARCMIN:
            return candidate
    return anchor


def _build_description(png: str, v84: Optional[Dict[str, str]]) -> str:
    parts = []
    if png and png not in ("possible", "rejected"):
        parts.append(f"PN G{png}")
    elif png:
        parts.append(f"Classified {png} in the Strasbourg-ESO catalogue")
    if v84 and v84["idents"]:
        parts.append(f"Also {v84['idents']}")
    return ". ".join(parts)


def load_pk():
    logging.info("Loading Perek-Kohoutek")
    assert objects_db is not None, "Database not initialized before load_pk()"
    conn, _ = objects_db.get_conn_cursor()

    delete_catalog_from_database(CATALOG_CODE)
    insert_catalog(CATALOG_CODE, DATA_DIR / "pk.desc")

    rows = _read_table2()
    table4_positions = _read_table4()
    simbad_positions = _read_simbad_positions()
    simbad_aliases = _read_simbad_aliases()
    v84_main = _read_v84_main()
    v84_sizes = _read_v84_diam()
    logging.info(
        "Perek-Kohoutek sources: %d rows, %d table4 positions, %d SIMBAD positions, "
        "%d SIMBAD cross-id sets, %d V/84 entries, %d V/84 sizes",
        len(rows),
        len(table4_positions),
        len(simbad_positions),
        len(simbad_aliases),
        len(v84_main),
        len(v84_sizes),
    )

    position_sources: Dict[str, int] = {}
    linked = 0

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)
    try:
        for sequence, row in enumerate(tqdm(rows), start=1):
            key = _pk_key(row["pk"])
            if key is None:
                raise ValueError(
                    f"Unparseable PK designation {row['pk']!r} at table2 line "
                    f"{sequence}"
                )

            anchor = Position(
                _hms_to_deg(float(row["ra_h"]), float(row["ra_m"])),
                _dms_to_deg(row["de_sign"], float(row["de_d"]), float(row["de_m"])),
                "IV/24 table2",
            )
            position_candidates = []
            if key in simbad_positions:
                position_candidates.append(simbad_positions[key])
            position_candidates.extend(table4_positions.get(key, []))
            position = _choose_position(position_candidates, anchor)
            position_sources[position.source] = (
                position_sources.get(position.source, 0) + 1
            )

            png = row["png"]
            v84 = v84_main.get(png)

            # Linking aliases lead, because find_object_id() takes the first
            # match: a resolvable NGC/IC/Messier designation must win over a
            # name that merely looks like one.
            linking: List[str] = []
            plain: List[str] = []
            alias_candidates = simbad_aliases.get(key, []) + [row["name"]]
            if v84:
                alias_candidates.append(v84["name"])
                alias_candidates.extend(v84["idents"].split(","))
            for candidate in alias_candidates:
                candidate_linking, candidate_plain = _designation_aliases(candidate)
                linking.extend(candidate_linking)
                plain.extend(candidate_plain)

            plain.extend(_pk_display_names(key))
            if png and png not in ("possible", "rejected"):
                plain.append(f"PN G{png}")
            if v84 and v84["iras"]:
                plain.append(f"IRAS {v84['iras']}")

            aka_names = list(dict.fromkeys(linking + plain))
            if linking:
                linked += 1

            new_object = NewCatalogObject(
                object_type=OBJECT_TYPE,
                catalog_code=CATALOG_CODE,
                sequence=sequence,
                ra=position.ra,
                dec=position.dec,
                mag=MagnitudeObject([]),
                size=v84_sizes.get(png, SizeObject([])),
                aka_names=aka_names,
                description=_build_description(png, v84),
            )
            new_object.insert()
    finally:
        NewCatalogObject.clear_shared_finder()

    logging.info("Perek-Kohoutek positions by source: %s", position_sources)
    logging.info(
        "Perek-Kohoutek entries carrying a linking designation: %d of %d",
        linked,
        len(rows),
    )

    insert_catalog_max_sequence(CATALOG_CODE)
    conn.commit()
