"""
Supplementary sources: published references that fill or replace fields on
the sky objects the loaders made, joined on a stable key. A supplementary
source never adds a catalog listing (ADR 0046, docs/ax/catalog.md section 9.4).

The import runs them after the loaders, post-processing and the star-identity
stage, and before the correction pass, so a correction still has the last
word:

- replace_hipparcos_values: Hipparcos replaces the position and the primary's
  V of every star the star-identity stage identified by its HIP number
  (astro_data/hip_main.dat).
- add_wgsn_names: the IAU Catalog of Star Names, joined on the same HIP
  numbers, makes each IAU name its star's preferred name (astro_data/iau_wgsn/).
- fill_bica_sizes: Bica et al. (2008) fills a missing size on a Magellanic
  object, and never replaces one (astro_data/bica2008/).
- replace_rc3_v_magnitudes: an extract of RC3's rows whose BT is coded "V"
  replaces Steinicke's V where Steinicke took that V-band magnitude for his
  Bmag (astro_data/rc3/).

Bica and RC3 are VizieR extracts, vendored verbatim with the queries that
fetched them; read_vizier_tsv reads them.
"""

import csv
import json
import logging
import math
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Mapping, Optional, Set, Tuple

import PiFinder.utils as utils
from PiFinder import calc_utils
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.db.objects_db import ObjectsDatabase
from .catalog_import_utils import (
    STAR_HIPS,
    MatchRejection,
    match_guard,
    parse_component,
    parse_designation,
    separation_arcmin,
)
from .corrections import parse_dec, parse_ra
from .post_processing import put_names_first
from .star_identity import RANGE_CATALOGS, Hipparcos, load_hipparcos
from .steinicke_loader import NOT_FOUND_DESCRIPTION, select_listings

WGSN_PATH = Path(utils.astro_data_dir) / "iau_wgsn" / "iau_csn.tsv"
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


# ---- Hipparcos: star positions and V ----

# Hipparcos's coarse variability flag (H6) for an amplitude over 0.6 mag
# (VizieR I/239, ReadMe): such a star's V is one value of its swing.
LARGE_AMPLITUDE_FLAG = 3


@dataclass
class HipparcosReplacement:
    """What replace_hipparcos_values did, star by star.

    `moved` is (object id, HIP, arcseconds moved) for every star whose
    position changed; `magnitudes` (object id, HIP, V before, V after) for
    every star whose primary's V changed, None before where it had none;
    `constellations` (object id, before, after). These keep their magnitude:
    `not_own_v`, (object id, HIP) where Hipparcos's V is not the star's own
    (a double's combined light, or another component's); `large_amplitude`,
    (object id, HIP) where Hipparcos flags a variability of more than 0.6 mag;
    `kept_range`, the stars whose magnitude is a variable's range; and `no_v`,
    those Hipparcos gives no V for.
    """

    replaced: int = 0
    moved: List[Tuple[int, int, float]] = field(default_factory=list)
    magnitudes: List[Tuple[int, int, Optional[float], float]] = field(
        default_factory=list
    )
    constellations: List[Tuple[int, str, str]] = field(default_factory=list)
    not_own_v: List[Tuple[int, int]] = field(default_factory=list)
    large_amplitude: List[Tuple[int, int]] = field(default_factory=list)
    kept_range: List[int] = field(default_factory=list)
    no_v: List[int] = field(default_factory=list)


def primary_v_replaced(mag: MagnitudeObject, vmag: float) -> MagnitudeObject:
    """The magnitudes with the first, the primary's, replaced by `vmag`.

    A companion's magnitude is untouched: a double star's [A, B] keeps B. A
    star with no magnitude gets the primary's.
    """
    return MagnitudeObject([vmag] + list(mag.mags[1:]))


def replace_hipparcos_values(
    db: ObjectsDatabase,
    hips: Optional[Mapping[int, int]] = None,
    hipparcos: Optional[Hipparcos] = None,
) -> HipparcosReplacement:
    """Replace each identified star's position and primary's V with Hipparcos's.

    `hips` maps a star sky object to the HIP number the star-identity stage
    identified it by (by position, by an exact identifier, or by a `hip`
    correction); it defaults to what that stage recorded in STAR_HIPS. No
    other star is touched, and nothing is matched here.

    The position becomes Hipparcos's, carried to J2000 by its proper motion
    (load_hipparcos), and the constellation follows it, as a loader computes
    it at insert. For a close double that is the pair's photocentre, which is
    as good at a finder's scale.

    The first magnitude, the primary's, becomes Hipparcos's V (H5) only where
    that V is the star's own (Hipparcos.own_vmag): for many doubles it is the
    combined light of the pair (Porrima's 2.74, for two stars of 3.5), which
    would put A and B's total in A's place. A companion's magnitude is
    untouched. These keep their magnitude: a star whose Hipparcos V is not its
    own; a variable of large amplitude (LARGE_AMPLITUDE_FLAG), or one whose
    sky object holds its range (TLK's [max, min]), since no one value of a
    variable's swing is the primary's V (SAC gives Mira's maximum, 2.0;
    Hipparcos 6.47); and one Hipparcos gives no V for.
    """
    hips = STAR_HIPS if hips is None else hips
    hipparcos = hipparcos if hipparcos is not None else load_hipparcos()
    if hipparcos.own_vmag is None:
        raise ValueError("Hipparcos was read without its photometry flags")
    result = HipparcosReplacement()
    cursor = db.conn.cursor()
    for object_id, hip in sorted(hips.items()):
        index = hipparcos.index_of(hip)
        if index is None:
            raise ValueError(f"object {object_id}: Hipparcos has no HIP {hip}")
        row = cursor.execute(
            "SELECT o.ra, o.dec, o.const, o.mag,"
            " (SELECT catalog_code FROM catalog_objects"
            "  WHERE object_id = o.id ORDER BY id LIMIT 1) AS first_catalog"
            " FROM objects o WHERE o.id = ?",
            (object_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"HIP {hip}: there is no object {object_id}")
        ra, dec = float(hipparcos.ra[index]), float(hipparcos.dec[index])
        const = calc_utils.sf_utils.radec_to_constellation(ra, dec)
        mag = MagnitudeObject.from_json(row["mag"])
        vmag = float(hipparcos.vmag[index])
        if row["first_catalog"] in RANGE_CATALOGS:
            result.kept_range.append(object_id)
        elif math.isnan(vmag):
            result.no_v.append(object_id)
        elif not hipparcos.own_vmag[index]:
            result.not_own_v.append((object_id, hip))
        elif hipparcos.var_flag[index] == LARGE_AMPLITUDE_FLAG:
            result.large_amplitude.append((object_id, hip))
        elif list(mag.mags[:1]) != [vmag]:
            before = mag.mags[0] if mag.mags and utils.is_number(mag.mags[0]) else None
            mag = primary_v_replaced(mag, vmag)
            result.magnitudes.append((object_id, hip, before, vmag))
        if (ra, dec) != (row["ra"], row["dec"]):
            moved = separation_arcmin(row["ra"], row["dec"], ra, dec) * 60
            result.moved.append((object_id, hip, moved))
        if const != row["const"]:
            result.constellations.append((object_id, row["const"], const))
            logging.info(
                "Hipparcos: HIP %d (object %d) moves from %s into %s",
                hip,
                object_id,
                row["const"],
                const,
            )
        cursor.execute(
            "UPDATE objects SET ra = ?, dec = ?, const = ?, mag = ? WHERE id = ?",
            (ra, dec, const, mag.to_json(), object_id),
        )
        result.replaced += 1
    db.conn.commit()
    logging.info(
        "Hipparcos: %d stars; %d positions moved, %d V replaced,"
        " %d constellations changed; V left as it is on %d stars whose"
        " Hipparcos V is not their own, %d variables of large amplitude,"
        " %d variable ranges and %d stars without a Hipparcos V",
        result.replaced,
        len(result.moved),
        len(result.magnitudes),
        len(result.constellations),
        len(result.not_own_v),
        len(result.large_amplitude),
        len(result.kept_range),
        len(result.no_v),
    )
    return result


# ---- IAU WGSN: star names ----

# The origin recorded on the names the WGSN adds.
WGSN_ORIGIN = "WGSN"


@dataclass
class WgsnName:
    """One name of the IAU Catalog of Star Names."""

    name: str
    hip: Optional[int]
    designation: str


@dataclass
class WgsnNames:
    """What add_wgsn_names did.

    `preferred` is (name, object id) for every name made a star's preferred
    name, of which `added` were new to the sky object and the rest moved
    first; `folded` is (name, its ASCII form) for every ASCII alias stored.
    `spellings` is (IAU name, the sky object's name) where the sky object
    already had the name spelled otherwise (diacritics, case), and
    `elsewhere` (name, other object ids) where another sky object has it too.
    The skipped names: no HIP number, a HIP number PiFinder holds no star
    for, and a HIP number with two names.
    """

    preferred: List[Tuple[str, int]] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    folded: List[Tuple[str, str]] = field(default_factory=list)
    spellings: List[Tuple[str, str]] = field(default_factory=list)
    elsewhere: List[Tuple[str, List[int]]] = field(default_factory=list)
    no_hip: List[str] = field(default_factory=list)
    not_held: List[str] = field(default_factory=list)
    shared_hip: List[str] = field(default_factory=list)


def read_wgsn(path: Path = WGSN_PATH) -> List[WgsnName]:
    """The names of iau_csn.tsv, in its order; extract.py writes it."""
    with open(path, encoding="utf-8", newline="") as tsv:
        return [
            WgsnName(
                name=row["name"],
                hip=int(row["hip"]) if row["hip"] else None,
                designation=row["designation"],
            )
            for row in csv.DictReader(tsv, delimiter="\t")
        ]


def ascii_folded(name: str) -> str:
    """The name without its diacritics: "Mönch" -> "Monch".

    Unicode's compatibility decomposition (NFKD) with the combining marks
    dropped, so the keypad's text search finds a name it can't type.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _spelling_key(name: str) -> str:
    """A name compared without diacritics, case, spaces or punctuation."""
    return "".join(char for char in ascii_folded(name).casefold() if char.isalnum())


def add_wgsn_names(
    db: ObjectsDatabase,
    hips: Optional[Mapping[int, int]] = None,
    path: Path = WGSN_PATH,
) -> WgsnNames:
    """Make each star's IAU name its preferred name, joined by HIP number.

    `hips` maps a star sky object to the HIP number the star-identity stage
    identified it by, and defaults to STAR_HIPS; a name joins only those, and
    nothing is matched here. The IAU name is placed first among the sky
    object's names (put_names_first), or moved first if it has it already,
    and its other names (Graffias, Tegmen) stay behind it as ordinary names,
    so text search still finds them. Where the IAU spelling has diacritics,
    its ASCII form is stored too, as an ordinary name.

    A name with no HIP number, one whose star PiFinder doesn't hold, and the
    names of a HIP number that has two (HIP 72105, Izar and Pulcherrima, with
    no component to choose between them) are skipped, and counted.
    """
    hips = STAR_HIPS if hips is None else hips
    object_of: Dict[int, int] = {}
    for star, hip in sorted(hips.items()):
        if hip in object_of:
            raise ValueError(
                f"HIP {hip} identifies objects {object_of[hip]} and {star}"
            )
        object_of[hip] = star
    names = read_wgsn(path)
    names_of_hip: Dict[int, List[str]] = defaultdict(list)
    for wgsn in names:
        if wgsn.hip is not None:
            names_of_hip[wgsn.hip].append(wgsn.name)

    result = WgsnNames()
    cursor = db.conn.cursor()
    for wgsn in names:
        if wgsn.hip is None:
            result.no_hip.append(wgsn.name)
            logging.debug("WGSN: %s (%s) has no HIP", wgsn.name, wgsn.designation)
            continue
        if len(names_of_hip[wgsn.hip]) > 1:
            result.shared_hip.append(wgsn.name)
            logging.info(
                "WGSN: HIP %d has two names, %s, so neither is added",
                wgsn.hip,
                " and ".join(names_of_hip[wgsn.hip]),
            )
            continue
        object_id = object_of.get(wgsn.hip)
        if object_id is None:
            result.not_held.append(wgsn.name)
            logging.debug("WGSN: PiFinder holds no HIP %d (%s)", wgsn.hip, wgsn.name)
            continue
        held = [
            row[0]
            for row in cursor.execute(
                "SELECT common_name FROM names WHERE object_id = ? ORDER BY id",
                (object_id,),
            )
        ]
        for name in held:
            if name != wgsn.name and _spelling_key(name) == _spelling_key(wgsn.name):
                result.spellings.append((wgsn.name, name))
                logging.info(
                    "WGSN: HIP %d's %s is spelled %s on object %d",
                    wgsn.hip,
                    wgsn.name,
                    name,
                    object_id,
                )
        if wgsn.name not in held:
            result.added.append(wgsn.name)
        put_names_first(cursor, object_id, [wgsn.name], WGSN_ORIGIN)
        result.preferred.append((wgsn.name, object_id))
        folded = ascii_folded(wgsn.name)
        if folded != wgsn.name:
            if not folded.isascii():
                logging.warning("WGSN: %s folds to %s, not ASCII", wgsn.name, folded)
            if folded not in held:
                cursor.execute(
                    "INSERT INTO names (object_id, common_name, origin)"
                    " VALUES (?, ?, ?)",
                    (object_id, folded, WGSN_ORIGIN),
                )
            result.folded.append((wgsn.name, folded))
        others = sorted(
            {
                row[0]
                for row in cursor.execute(
                    "SELECT object_id FROM names WHERE common_name IN (?, ?)"
                    " AND object_id != ?",
                    (wgsn.name, folded, object_id),
                )
            }
        )
        if others:
            result.elsewhere.append((wgsn.name, others))
            logging.info(
                "WGSN: %s (HIP %d, object %d) is also a name of objects %s",
                wgsn.name,
                wgsn.hip,
                object_id,
                ", ".join(map(str, others)),
            )
    db.conn.commit()
    logging.info(
        "WGSN: %d preferred names (%d new to their star, %d ASCII forms added);"
        " skipped %d without a HIP number, %d for stars PiFinder doesn't hold,"
        " %d on a HIP number with two names",
        len(result.preferred),
        len(result.added),
        len(result.folded),
        len(result.no_hip),
        len(result.not_held),
        len(result.shared_hip),
    )
    return result


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
