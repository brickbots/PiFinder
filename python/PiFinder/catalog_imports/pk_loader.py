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

Design notes live in docs/adr/0045-perek-kohoutek-catalog.md.
"""

import csv
import logging
import math
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

from tqdm import tqdm

import PiFinder.utils as utils
from PiFinder.calc_utils import dms_to_dec, ra_to_deg
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
# resolving to the wrong object. IV/24 table4 carries at least one: an
# equinox-2000 row for Vy 1-4 reads -02 26, where its five sibling rows and
# SIMBAD all read -06 26.
POSITION_AGREEMENT_ARCMIN = 5.0

# A cross-link joins an entry to an existing sky object. It is accepted only
# when that object lies within this distance of the entry's position. The
# largest offset among the correct links is 17 arcminutes (large nebulae that
# two catalogues centre differently); a wrong link is degrees away.
LINK_AGREEMENT_ARCMIN = 30.0

# Prefixes this source uses for PiFinder catalogs beyond the shared ones:
# V/84 writes Abell planetaries as "A 50".
SOURCE_ALIASES = {"a": "Abl"}

# The PNG column of IV/24 table2 holds the Strasbourg-ESO (V/84) designation,
# or one of these words for a nebula that has none.
SECG_STATUS = {
    "poss.": "Possible PN in the Strasbourg-ESO catalogue",
    "rej.": "Rejected as a PN by the Strasbourg-ESO catalogue",
    "--": "Not in the Strasbourg-ESO catalogue",
}


class Position(NamedTuple):
    ra: float
    dec: float
    source: str


def _field(line: str, start: int, end: int) -> str:
    """One fixed-width field, using the ReadMe's 1-based inclusive byte range."""
    return line[start - 1 : end].strip()


def _pk_key(raw: str) -> Optional[str]:
    """Canonical join key for a PK designation.

    Each source spells it differently: "036+17.1" in IV/24, "036+17  1" in
    SIMBAD, "171-25 1" in V/84. So reduce them all to "036+17.1".
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
    parsed = parse_designation(name, extra_aliases=SOURCE_ALIASES)
    if parsed is not None:
        catalog_code, sequence = parsed
        linking.append(f"{catalog_code} {sequence}")
    elif name.upper().startswith("NGC "):
        linking.extend(_ngc_pair(name[4:]))

    return linking, [name]


def _split_idents(field: str) -> List[str]:
    """Split a V/84 cross-identification field on its commas.

    The field lists one designation per comma, but one row writes
    "NGC,6742": a token without a digit, then a token of only digits. Such
    a pair is one designation, so it is joined again ("NGC 6742"). Tokens
    without digits that stand alone, like the Blanco names "Bl G", stay.
    """
    idents: List[str] = []
    for token in (t.strip() for t in field.split(",")):
        if not token:
            continue
        if token.isdigit() and idents and not any(ch.isdigit() for ch in idents[-1]):
            idents[-1] = f"{idents[-1]} {token}"
        else:
            idents.append(token)
    return idents


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
    """IV/24/table2: the authoritative 1510 rows, ordered by right ascension."""
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
    """IV/24/table4: arcsecond J2000 positions, several rows per nebula.

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
                    ra_to_deg(float(ra_h), float(ra_m), float(ra_s or 0)),
                    dms_to_dec(
                        _field(line, 94, 94) or "+",
                        int(de_d),
                        int(de_m),
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
    """V/84/diam: optical diameter preferred, radio diameter as fallback."""
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


def _secg_designation(png: str) -> Optional[str]:
    """The Strasbourg-ESO designation from the PNG column, or None when the
    column holds a status word (see SECG_STATUS) or is empty."""
    if not png or png in SECG_STATUS:
        return None
    return png


def _build_description(png: str, f_pk: str, v84: Optional[Dict[str, str]]) -> str:
    parts = []
    designation = _secg_designation(png)
    if designation:
        parts.append(f"PN G{designation}")
    elif png in SECG_STATUS:
        parts.append(SECG_STATUS[png])
    if f_pk == "*":
        parts.append("Kohoutek lists it as a possible PN")
    if v84 and v84["idents"]:
        parts.append(f"Also {', '.join(_split_idents(v84['idents']))}")
    return ". ".join(parts)


def _linked_object_id(
    finder: ObjectFinder, names: List[str], position: Position
) -> Optional[int]:
    """The sky object the first resolvable name links to, when that object
    lies within LINK_AGREEMENT_ARCMIN of ``position``. A name that resolves
    to an object farther away is logged and skipped."""
    assert objects_db is not None, "Database not initialized"
    for name in names:
        object_id = finder.get_object_id(name)
        if object_id is None:
            continue
        row = objects_db.get_object_by_id(object_id)
        target = Position(row["ra"], row["dec"], f"object {object_id}")
        separation = angular_separation_arcmin(target, position)
        if separation <= LINK_AGREEMENT_ARCMIN:
            return object_id
        logging.warning(
            "Perek-Kohoutek: %r resolves to object %d, %.0f arcmin away; not linked",
            name,
            object_id,
            separation,
        )
    return None


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
                ra_to_deg(float(row["ra_h"]), float(row["ra_m"]), 0.0),
                dms_to_dec(row["de_sign"], int(row["de_d"]), int(row["de_m"]), 0.0),
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
            designation = _secg_designation(png)
            v84 = v84_main.get(designation) if designation else None

            # Linking aliases lead, because find_object_id() takes the first
            # match: a resolvable NGC/IC/Messier designation must win over a
            # name that merely looks like one.
            linking: List[str] = []
            plain: List[str] = []
            # SIMBAD aliases only when SIMBAD also calls the object a PN: for
            # another object type, its aliases can name a galaxy or a cluster.
            alias_candidates = (
                simbad_aliases.get(key, []) if key in simbad_positions else []
            ) + [row["name"]]
            if v84:
                alias_candidates.append(v84["name"])
                alias_candidates.extend(_split_idents(v84["idents"]))
            for candidate in alias_candidates:
                candidate_linking, candidate_plain = _designation_aliases(candidate)
                linking.extend(candidate_linking)
                plain.extend(candidate_plain)

            plain.extend(_pk_display_names(key))
            if designation:
                plain.append(f"PN G{designation}")
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
                size=v84_sizes.get(designation, SizeObject([])),
                aka_names=aka_names,
                description=_build_description(png, row["f_pk"], v84),
            )
            new_object.object_id = (
                _linked_object_id(shared_finder, aka_names, position) or 0
            )
            new_object.insert(find_object_id=False)
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
