"""
Supplementary sources: published references that fill or replace fields on
the sky objects the loaders made, joined on a stable key. A supplementary
source never adds a catalog listing (ADR 0046, docs/ax/catalog.md section 9.4).

The import runs them after the loaders and post-processing, and before the
correction pass, so a correction still has the last word:

- fill_bica_sizes: Bica et al. (2008) fills a missing size on a Magellanic
  object, and never replaces one (astro_data/bica2008/).
- replace_rc3_v_magnitudes: an extract of RC3's rows whose BT is coded "V"
  replaces Steinicke's V where Steinicke took that V-band magnitude for his
  Bmag (astro_data/rc3/).

Both sources are VizieR extracts, vendored verbatim with the queries that
fetched them; read_vizier_tsv reads them.
"""

import json
import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

import PiFinder.utils as utils
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.db.objects_db import ObjectsDatabase
from .catalog_import_utils import (
    MatchRejection,
    match_guard,
    parse_component,
    parse_designation,
    separation_arcmin,
)
from .corrections import parse_dec, parse_ra
from .steinicke_loader import NOT_FOUND_DESCRIPTION, select_listings

BICA_PATH = Path(utils.astro_data_dir) / "bica2008" / "bica2008_ngc_ic.tsv"
RC3_PATH = Path(utils.astro_data_dir) / "rc3" / "rc3_bt_code_v.tsv"
# Extracted from steinicke_catalog_source.zip by the Steinicke loader, which
# runs first.
STEINICKE_PATH = (
    Path(utils.astro_data_dir) / "ngc_ic_m" / "steinicke" / "steinicke_catalog.json"
)

# Steinicke's Bmag is RC3's V-coded BT when the two agree within this. Both
# are rounded (Steinicke to 0.1, RC3 to 0.01), so the slack keeps a difference
# of exactly 0.05 a match.
RC3_BT_TOLERANCE = 0.05
_FLOAT_SLACK = 1e-9

NGC_IC = ("NGC", "IC")

Designation = Tuple[str, int, str]  # ("NGC", 78, "A"); the letter may be ""


def read_vizier_tsv(path: Path) -> Iterator[Tuple[str, Dict[str, str]]]:
    """The rows of one or more VizieR ASU-TSV responses, as (table, row).

    A response's comment lines start with "#", one of them "#Table <name>:".
    Each table's rows follow a line of column names, a line of units and a
    line of dashes, and end at a blank line. Values are stripped of the
    padding VizieR adds; the table is its name ("J_MNRAS_389_678_table3").
    """
    table = ""
    columns: Optional[List[str]] = None
    under_header = 0
    with open(path, encoding="utf-8") as tsv:
        for line in tsv:
            line = line.rstrip("\r\n")
            if under_header:
                # The units line, which may be blank, then the dashes.
                under_header -= 1
                continue
            if line.startswith("#"):
                if line.startswith("#Table\t"):
                    table = line.split("\t")[1].rstrip(":")
                continue
            if not line.strip():
                columns = None
                continue
            if columns is None:
                columns = line.split("\t")
                under_header = 2
                continue
            values = [value.strip() for value in line.split("\t")]
            yield table, dict(zip(columns, values))


def ngc_ic_designation(name: str) -> Optional[Designation]:
    """An NGC or IC designation with its letter: "NGC    78A" -> ("NGC", 78, "A").

    The same reading the loaders give a name (parse_designation, and
    parse_component for a single trailing letter), limited to NGC and IC.
    None for any other name, and for Bica's two-letter halves of a pair
    ("NGC460nw").
    """
    parsed = parse_designation(name)
    designation = (
        (parsed[0], parsed[1], "") if parsed is not None else parse_component(name)
    )
    if designation is None or designation[0] not in NGC_IC:
        return None
    return designation


def _listing_object(
    cursor: sqlite3.Cursor, catalog_code: str, sequence: int
) -> Optional[sqlite3.Row]:
    """The sky object of a catalog listing, with that listing's description."""
    return cursor.execute(
        "SELECT o.id, o.obj_type, o.ra, o.dec, o.size, o.mag, co.description"
        " FROM catalog_objects co JOIN objects o ON o.id = co.object_id"
        " WHERE co.catalog_code = ? AND co.sequence = ?",
        (catalog_code, sequence),
    ).fetchone()


# ---- Bica et al. (2008): sizes ----


@dataclass
class BicaObject:
    """One row of Bica et al. (2008): a Magellanic cluster, association or nebula."""

    names: List[str]
    ra: float
    dec: float
    bica_type: str  # Bica's class code: C, CN, A, NA, DNC...
    size: SizeObject

    @property
    def label(self) -> str:
        return f"Bica 2008 {','.join(self.names)}"

    def listings(self) -> List[Tuple[str, int]]:
        """The NGC and IC numbers its names name, unlettered: ("NGC", 1966)."""
        listings = []
        for name in self.names:
            designation = ngc_ic_designation(name)
            if designation is not None and not designation[2]:
                listings.append(designation[:2])
        return listings


@dataclass
class BicaFill:
    """What fill_bica_sizes did: designators filled, joins refused."""

    filled: List[str] = field(default_factory=list)
    rejected: List[MatchRejection] = field(default_factory=list)
    not_found: List[str] = field(default_factory=list)


def read_bica(path: Path = BICA_PATH) -> List[BicaObject]:
    """Bica's rows, each once: a row naming both an NGC and an IC number is
    in both of its table's responses."""
    objects = []
    seen = set()
    for table, row in read_vizier_tsv(path):
        key = (table, row["Names"], row["RAJ2000"], row["DEJ2000"])
        if key in seen or not row["amaj"]:
            continue
        seen.add(key)
        axes = sorted(
            (float(axis) for axis in (row["amaj"], row["amin"]) if axis),
            reverse=True,
        )
        position_angle = float(row["PA"]) if row["PA"] else 0.0
        objects.append(
            BicaObject(
                names=[
                    name.strip() for name in row["Names"].split(",") if name.strip()
                ],
                ra=parse_ra(row["RAJ2000"]),
                dec=parse_dec(row["DEJ2000"]),
                bica_type=row["Type"],
                size=SizeObject.from_arcmin(*axes, position_angle=position_angle),
            )
        )
    return objects


def fill_bica_sizes(db: ObjectsDatabase, path: Path = BICA_PATH) -> BicaFill:
    """Fill a missing size from Bica et al. (2008); never replace one.

    Each NGC or IC number in a row's names joins its listing's sky object, if
    that sky object has no size and the join passes the loaders' match guard:
    Steinicke and Bica disagree about some identifications (they swap NGC 2029
    and NGC 2030, 91' apart), and Bica's clusters and nebulae never join a
    star. A not-found object is skipped, since only an identification places
    one. Where two rows reach one sky object (Steinicke makes NGC 1911 a
    duplicate of NGC 1920; Bica lists them apart), the nearer row fills it.
    """
    result = BicaFill()
    cursor = db.conn.cursor()
    candidates: Dict[int, List[Tuple[float, str, BicaObject]]] = defaultdict(list)
    for bica in read_bica(path):
        reached: Set[int] = set()
        for catalog_code, sequence in bica.listings():
            designator = f"{catalog_code} {sequence}"
            sky_object = _listing_object(cursor, catalog_code, sequence)
            if sky_object is None:
                logging.debug("%s: PiFinder has no %s", bica.label, designator)
                continue
            if sky_object["id"] in reached:
                # Its NGC and IC numbers name one sky object (NGC1748,IC2114)
                continue
            reached.add(sky_object["id"])
            if SizeObject.from_json(sky_object["size"]).extents:
                continue
            if (sky_object["description"] or "").startswith(NOT_FOUND_DESCRIPTION):
                result.not_found.append(designator)
                logging.info(
                    "%s: %s is a not-found object, so no size", bica.label, designator
                )
                continue
            reason = match_guard(bica.bica_type, bica.ra, bica.dec, sky_object)
            if reason is not None:
                rejection = MatchRejection(
                    bica.label, designator, sky_object["id"], reason
                )
                result.rejected.append(rejection)
                logging.warning(
                    "Match guard: %s does not fill %s (object %d): %s",
                    bica.label,
                    designator,
                    sky_object["id"],
                    reason,
                )
                continue
            separation = separation_arcmin(
                bica.ra, bica.dec, sky_object["ra"], sky_object["dec"]
            )
            candidates[sky_object["id"]].append((separation, designator, bica))

    for object_id, found in candidates.items():
        _, designator, bica = min(found, key=lambda candidate: candidate[0])
        if len(found) > 1:
            logging.info(
                "%s fills object %d, the nearest of %s",
                bica.label,
                object_id,
                ", ".join(candidate[2].label for candidate in found),
            )
        cursor.execute(
            "UPDATE objects SET size = ? WHERE id = ?",
            (bica.size.to_json(), object_id),
        )
        result.filled.append(designator)
    db.conn.commit()
    logging.info(
        "Bica 2008 filled %d sizes; the match guard refused %d joins;"
        " %d not-found objects skipped",
        len(result.filled),
        len(result.rejected),
        len(result.not_found),
    )
    return result


# ---- RC3: V-coded BT ----


@dataclass
class RC3Replacement:
    """What replace_rc3_v_magnitudes did: (designator, V before, V after)."""

    replaced: List[Tuple[str, float, float]] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


def read_rc3_v_coded(path: Path = RC3_PATH) -> Dict[Designation, float]:
    """RC3's V-coded BT by NGC/IC designation, letter included.

    ("NGC", 78, "A") -> 13.68. Rows without an NGC or IC name are left out.
    """
    magnitudes = {}
    for _table, row in read_vizier_tsv(path):
        designation = ngc_ic_designation(row["name"])
        if designation is not None and row["BT_code"] == "V":
            magnitudes[designation] = float(row["BT"])
    return magnitudes


def steinicke_listings(path: Path = STEINICKE_PATH) -> Dict[Tuple[str, int], dict]:
    """The Steinicke row the loader keeps for each NGC and IC number."""
    with open(path, encoding="utf-8") as f:
        return select_listings(json.load(f))


def replace_rc3_v_magnitudes(
    db: ObjectsDatabase,
    path: Path = RC3_PATH,
    steinicke: Optional[Dict[Tuple[str, int], dict]] = None,
) -> RC3Replacement:
    """Replace Steinicke's V with his Bmag where that Bmag is RC3's V-coded BT.

    RC3 codes some BT values "V": they are V-band magnitudes. Where
    Steinicke's Bmag equals one within RC3_BT_TOLERANCE, he took it for B and
    subtracted a colour, so his V is about 1 mag too bright and his Bmag is
    the V.

    Each RC3 name joins, letter included, the Steinicke row the loader keeps
    for that number: RC3's NGC 78A is that row, listed as NGC 78. Steinicke's
    Bmag comes from that row in steinicke_catalog.json (``steinicke``, keyed
    as select_listings keys it), not from the database, which doesn't hold it.

    The V is replaced only on a sky object that still holds that row's V, the
    value this fixes. Steinicke's Bmag is never a fallback: a row with no V
    leaves the sky object as it is.
    """
    if steinicke is None:
        steinicke = steinicke_listings()
    rc3 = read_rc3_v_coded(path)
    result = RC3Replacement()
    cursor = db.conn.cursor()
    for (prefix, number), row in steinicke.items():
        catalog_code = "NGC" if prefix == "N" else "IC"
        bt = rc3.get((catalog_code, number, row.get("extension_letter") or ""))
        bmag = row.get("blue_magnitude")
        if (
            bt is None
            or bmag is None
            or abs(bmag - bt) > RC3_BT_TOLERANCE + _FLOAT_SLACK
        ):
            continue
        designator = f"{catalog_code} {number}"
        vmag = row.get("visual_magnitude")
        if vmag is None:
            result.skipped.append(designator)
            logging.info("RC3: %s has no Steinicke V to replace", designator)
            continue
        sky_object = _listing_object(cursor, catalog_code, number)
        if sky_object is None:
            logging.warning("RC3: PiFinder has no %s", designator)
            continue
        held = MagnitudeObject.from_json(sky_object["mag"])
        if len(held.mags) != 1 or abs(held.filter_mag - vmag) > _FLOAT_SLACK:
            result.skipped.append(designator)
            logging.warning(
                "RC3: %s holds %s, not Steinicke's V %s, so it is left as it is",
                designator,
                held.mags,
                vmag,
            )
            continue
        cursor.execute(
            "UPDATE objects SET mag = ? WHERE id = ?",
            (MagnitudeObject([bmag]).to_json(), sky_object["id"]),
        )
        result.replaced.append((designator, vmag, bmag))
    db.conn.commit()
    logging.info(
        "RC3 replaced %d V magnitudes with Steinicke's Bmag", len(result.replaced)
    )
    return result
