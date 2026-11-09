"""
Star identity: a star is identified by its Hipparcos number.

The star catalogs (Str, SaM, SaR, TLK, RDS, WDS) list many of the same stars,
and few of their listings carry a designation the loaders' lookup resolves, so
each loader leaves a star a sky object of its own: Mizar was SaM's and Str's.
This stage cross-matches each star sky object to hip_main.dat and merges the
sky objects that match one HIP number into one, typed by the D* rule
(docs/ax/catalog.md §9.3). It runs after post-processing and before the
supplementary sources and the correction pass (§9.1).

A match is made only where it is reliably right; a star the rules miss is
matched by a `hip` correction, which names the Hipparcos number of a listing
(ADR 0046, decision 4). This stage reads them before it cross-matches and uses
each in place of position.
"""

import logging
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

import PiFinder.utils as utils
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.db.objects_db import ObjectsDatabase
from .catalog_import_utils import STAND_IN_POSITIONS, fill_sky_object, merge_sky_object
from .corrections import CorrectionError, parse_designator, resolve_listing

# The catalogs whose listings are stars, in loader order.
STAR_CATALOGS = ("SaM", "SaR", "Str", "RDS", "TLK", "WDS")

# A match is made only where it is reliably right, at the cost of missing
# some stars; those are matched by `hip` corrections (catalog.md §9.3). The
# rules below each removed the wrong matches the evidence found.
#
# The radius follows the precision of a listing's position: 3' for SAC, RASC
# and the bright stars, which round to 0.1m in RA and 1' in Dec, and 3" for
# the arcsecond positions of WDS and TLK. A listing whose position stands in
# for its star's (STAND_IN_POSITIONS: a WDS row its identifier places, a SAC
# companion pair at its system's position) is not matched at all.
MATCH_RADIUS_ARCMIN = 3.0
PRECISE_MATCH_RADIUS_ARCMIN = 0.05
PRECISE_CATALOGS = frozenset({"WDS", "TLK"})

# The V gate: a listing's V must lie within this of the Hipparcos star's, or
# for a variable listed by its range (TLK's [max, min]), the Hipparcos star's
# V within this of the range. A listing without a V is not matched, and
# neither is one that two stars within the radius pass: a pair whose
# components each have a Hipparcos entry (61 Oph, ε Equ) is ambiguous.
V_TOLERANCE = 1.0
RANGE_CATALOGS = frozenset({"TLK"})

# A match must not contradict the listing's own designations: its HD, BD, CD
# or CPD numbers must include the matched star's in Hipparcos's own columns,
# and a double-star designation (SAC's "STF 362") that a WDS listing within
# this distance carries must not place the pair at another star.
VETO_RADIUS_ARCMIN = 15.0
# How far from the matched star the pair's WDS listing may lie: WDS's
# arcsecond positions sit on their star, though a few are 20" off (HDS 2003,
# Arcturus).
WDS_PAIR_SLACK_ARCMIN = 0.5
# SAC writes some discoverers as words where WDS abbreviates them, and "h"
# (John Herschel) apart from "H" (William Herschel, whose class WDS adds).
DISCOVERER_SPELLINGS = {
    "h": "HJ",
    "Howe": "HWE",
    "Stone": "STN",
    "Sh": "SHJ",
    "Dunlop": "DUN",
    "Burnham": "BU",
    "South": "S",
}
# Prefixes that are catalog numbers, not double-star discoverers.
_NOT_DISCOVERERS = frozenset(
    {"HD", "HR", "SAO", "HIP", "BD", "CD", "CPD", "COD", "NGC", "IC", "M", "ADS"}
    | {code.upper() for code in ("SaM", "SaR", "Str", "RDS", "TLK", "WDS", "H")}
)
_DESIGNATION_RE = re.compile(r"([A-Za-z]{1,8})\s*(\d+)")
_HD_RE = re.compile(r"HD\s*(\d+)")
_DM_RE = re.compile(r"(BD|CD|CoD|CPD)\s*([+-])\s*(\d+)\s+(\d+)\w?")

# Hipparcos positions are for J1991.25; the sources give J2000.
HIPPARCOS_EPOCH = 1991.25
SOURCE_EPOCH = 2000.0
_MAS_PER_DEGREE = 3.6e6

# The fields of hip_main.dat this stage reads, by position (VizieR I/239):
# H1 the HIP number, H3/H4 the position in h m s and d m s, H5 V, H6 the
# variability flag, H8/H9 the position in degrees (blank for the 263 stars
# with no astrometric solution, such as ξ UMa), H12/H13 the proper motion
# in mas/yr, the RA component times cos(Dec), and H71-H74 the star's HD, BD,
# CD and CPD numbers.
_HIP_FIELDS = {
    1: "hip",
    3: "ra_hms",
    4: "dec_dms",
    5: "vmag",
    6: "var_flag",
    8: "ra",
    9: "dec",
    12: "pm_ra",
    13: "pm_dec",
    71: "HD",
    72: "BD",
    73: "CD",
    74: "CPD",
}

# A catalog number, as a hashable key: ("HD", 12345) or ("BD", "+", 0, 5077).
CatalogNumber = Tuple


@dataclass
class Hipparcos:
    """The Hipparcos stars, at J2000 by their proper motion."""

    hip: np.ndarray
    ra: np.ndarray
    dec: np.ndarray
    vmag: np.ndarray
    var_flag: np.ndarray
    # Each HIP number's HD, BD, CD and CPD numbers, and the reverse.
    numbers_of: Dict[int, Set[CatalogNumber]] = field(default_factory=dict)
    star_with: Dict[CatalogNumber, int] = field(default_factory=dict)
    _tree: Optional[cKDTree] = field(default=None, init=False, repr=False)
    _index: Optional[Dict[int, int]] = field(default=None, init=False, repr=False)

    @property
    def tree(self) -> cKDTree:
        if self._tree is None:
            self._tree = cKDTree(unit_vectors(self.ra, self.dec))
        return self._tree

    def index_of(self, hip: int) -> Optional[int]:
        if self._index is None:
            self._index = {int(number): i for i, number in enumerate(self.hip)}
        return self._index.get(hip)


def unit_vectors(ra: np.ndarray, dec: np.ndarray) -> np.ndarray:
    ra, dec = np.radians(ra), np.radians(dec)
    return np.column_stack(
        [np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)]
    )


def _chord(arcmin: float) -> float:
    """The straight-line distance between unit vectors this far apart."""
    return 2 * np.sin(np.radians(arcmin / 60) / 2)


def _arcmin(chord: np.ndarray) -> np.ndarray:
    return np.degrees(2 * np.arcsin(np.clip(chord / 2, 0, 1))) * 60


def _sexagesimal(text: str) -> float:
    """'02 19 20.79' or '-02 58 37.4' to hours or degrees."""
    parts = text.split()
    value = abs(float(parts[0])) + float(parts[1]) / 60 + float(parts[2]) / 3600
    return -value if text.strip().startswith("-") else value


def dm_number(system: str, text: str) -> Optional[CatalogNumber]:
    """A Durchmusterung number as a key: ("BD", "+", 0, 5077) for "B+00 5077"."""
    match = re.search(r"([+-])\s*(\d+)\s+(\d+)", text)
    if match is None:
        return None
    return (system, match.group(1), int(match.group(2)), int(match.group(3)))


def catalog_numbers(name: str) -> List[CatalogNumber]:
    """The HD, BD, CD and CPD numbers a listing's name gives."""
    match = _HD_RE.fullmatch(name.strip())
    if match:
        return [("HD", int(match.group(1)))]
    match = _DM_RE.fullmatch(name.strip())
    if match:
        system = "CD" if match.group(1) == "CoD" else match.group(1)
        number = dm_number(system, " ".join(match.group(2, 3, 4)))
        return [number] if number else []
    return []


def load_hipparcos(path: Optional[Path] = None) -> Hipparcos:
    """Read hip_main.dat, with each position carried to J2000."""
    path = path or Path(utils.astro_data_dir, "hip_main.dat")
    frame = pd.read_csv(
        path,
        sep="|",
        header=None,
        usecols=list(_HIP_FIELDS),
        skipinitialspace=True,
        dtype={71: str, 72: str, 73: str, 74: str},
    ).rename(columns=_HIP_FIELDS)
    ra = frame["ra"].to_numpy(dtype=float)
    dec = frame["dec"].to_numpy(dtype=float)
    unsolved = np.isnan(ra)
    ra[unsolved] = [15 * _sexagesimal(text) for text in frame["ra_hms"][unsolved]]
    dec[unsolved] = [_sexagesimal(text) for text in frame["dec_dms"][unsolved]]
    years = SOURCE_EPOCH - HIPPARCOS_EPOCH
    pm_ra = np.nan_to_num(frame["pm_ra"].to_numpy(dtype=float))
    pm_dec = np.nan_to_num(frame["pm_dec"].to_numpy(dtype=float))
    dec_2000 = dec + pm_dec * years / _MAS_PER_DEGREE
    ra_2000 = ra + pm_ra * years / _MAS_PER_DEGREE / np.cos(np.radians(dec))
    numbers_of: Dict[int, Set[CatalogNumber]] = {}
    star_with: Dict[CatalogNumber, int] = {}
    columns = [frame[column].tolist() for column in ("HD", "BD", "CD", "CPD")]
    for number, hd, *dms in zip(frame["hip"].tolist(), *columns):
        numbers: Set[CatalogNumber] = set()
        if isinstance(hd, str) and hd.strip():
            numbers.add(("HD", int(hd)))
        for system, text in zip(("BD", "CD", "CPD"), dms):
            dm = dm_number(system, text) if isinstance(text, str) else None
            if dm:
                numbers.add(dm)
        numbers_of[int(number)] = numbers
        for catalog_number in numbers:
            star_with[catalog_number] = int(number)
    return Hipparcos(
        hip=frame["hip"].to_numpy(dtype=int),
        ra=np.mod(ra_2000, 360),
        dec=dec_2000,
        vmag=frame["vmag"].to_numpy(dtype=float),
        var_flag=np.nan_to_num(frame["var_flag"].to_numpy(dtype=float)).astype(int),
        numbers_of=numbers_of,
        star_with=star_with,
    )


@dataclass
class StarObject:
    """A sky object with a listing in a star catalog, as the loaders left it."""

    object_id: int
    # The catalog of its first listing, whose position and magnitude it holds.
    catalog_code: str
    ra: float
    dec: float
    mag: MagnitudeObject
    size: SizeObject
    obj_type: str
    # Whether its catalog gives arcsecond positions (WDS, TLK), and whether
    # its position stands in for its star's (STAND_IN_POSITIONS).
    precise: bool = False
    stand_in: bool = False
    listings: List[str] = field(default_factory=list)
    names: List[str] = field(default_factory=list)

    @property
    def vmag(self) -> Optional[float]:
        """The V the gate compares: the first magnitude, the primary's."""
        mags = self.numeric_mags
        return mags[0] if mags else None

    @property
    def numeric_mags(self) -> List[float]:
        return [float(m) for m in self.mag.mags if utils.is_number(m)]

    @property
    def radius_arcmin(self) -> Optional[float]:
        """The match radius, or None for a listing that is not matched."""
        if self.stand_in:
            return None
        return PRECISE_MATCH_RADIUS_ARCMIN if self.precise else MATCH_RADIUS_ARCMIN


def read_star_objects(
    cursor: sqlite3.Cursor, stand_in: Optional[Set[Tuple[str, int]]] = None
) -> Dict[int, StarObject]:
    """Every sky object with a star catalog's listing, by object id.

    `stand_in` names the listings whose position stands in for their star's;
    it defaults to what the loaders recorded in STAND_IN_POSITIONS.
    """
    stand_in = STAND_IN_POSITIONS if stand_in is None else stand_in
    codes = ", ".join("?" * len(STAR_CATALOGS))
    rows = cursor.execute(
        "SELECT o.id, o.obj_type, o.ra, o.dec, o.mag, o.size,"
        " c.catalog_code, c.sequence FROM objects o"
        " JOIN catalog_objects c ON c.object_id = o.id"
        " WHERE o.id IN (SELECT object_id FROM catalog_objects"
        f" WHERE catalog_code IN ({codes}))"
        " ORDER BY o.id, c.id",
        STAR_CATALOGS,
    ).fetchall()
    stars: Dict[int, StarObject] = {}
    for row in rows:
        star = stars.get(row["id"])
        if star is None:
            listing = (row["catalog_code"], row["sequence"])
            star = stars[row["id"]] = StarObject(
                object_id=row["id"],
                catalog_code=row["catalog_code"],
                ra=row["ra"],
                dec=row["dec"],
                mag=MagnitudeObject.from_json(row["mag"]),
                size=SizeObject.from_json(row["size"]),
                obj_type=row["obj_type"],
                precise=row["catalog_code"] in PRECISE_CATALOGS,
                stand_in=listing in stand_in,
            )
        star.listings.append(f"{row['catalog_code']} {row['sequence']}")
    for row in cursor.execute(
        "SELECT object_id, common_name FROM names WHERE object_id IN"
        f" (SELECT object_id FROM catalog_objects WHERE catalog_code IN ({codes}))"
        " ORDER BY id",
        STAR_CATALOGS,
    ):
        stars[row["object_id"]].names.append(row["common_name"])
    return stars


@dataclass
class Match:
    """A star sky object's Hipparcos star, or why it has none."""

    object_id: int
    hip: Optional[int] = None
    separation_arcmin: Optional[float] = None
    # Why there is no match: "no V", "V gate", "ambiguous", or a veto.
    reason: Optional[str] = None
    # The Hipparcos stars within the radius that pass the V gate.
    candidates: List[int] = field(default_factory=list)
    by_correction: bool = False


def passes_v_gate(star: StarObject, hip_vmag: float) -> bool:
    """Whether a listing's V agrees with a Hipparcos star's (V_TOLERANCE).

    A variable listed by its range passes when the Hipparcos star's V lies
    within V_TOLERANCE of the range. Without a V on either side there is
    nothing to compare, and no match.
    """
    mags = star.numeric_mags
    if not mags or np.isnan(hip_vmag):
        return False
    if star.catalog_code in RANGE_CATALOGS:
        low, high = min(mags), max(mags)
    else:
        low = high = mags[0]
    return low - V_TOLERANCE <= hip_vmag <= high + V_TOLERANCE


def cross_match(
    stars: Mapping[int, StarObject],
    hipparcos: Hipparcos,
    radius_scale: float = 1.0,
) -> Dict[int, Match]:
    """Each star sky object's Hipparcos star: the one star within its radius
    that passes the V gate. None passes, or two do: no match.
    `radius_scale` widens every radius, to see what lies just outside it."""
    stars_list = [star for star in stars.values() if star.radius_arcmin is not None]
    matches: Dict[int, Match] = {
        star.object_id: Match(star.object_id, reason="position not to be matched")
        for star in stars.values()
        if star.radius_arcmin is None
    }
    if not stars_list:
        return matches
    vectors = unit_vectors(
        np.array([star.ra for star in stars_list]),
        np.array([star.dec for star in stars_list]),
    )
    radii = np.array(
        [float(star.radius_arcmin or 0) * radius_scale for star in stars_list]
    )
    for radius in np.unique(radii):
        chosen = np.flatnonzero(radii == radius)
        found = hipparcos.tree.query_ball_point(vectors[chosen], _chord(radius))
        for i, near in zip(chosen, found):
            star = stars_list[i]
            match = matches[star.object_id] = Match(star.object_id)
            if star.vmag is None:
                match.reason = "no V"
                continue
            if not near:
                match.reason = "nothing within the radius"
                continue
            near = np.array(near)
            separations = _arcmin(
                np.linalg.norm(hipparcos.tree.data[near] - vectors[i], axis=1)
            )
            # Nearest first, ties to the lower HIP, so the record reads the
            # same in every import.
            order = np.lexsort((hipparcos.hip[near], separations))
            passing = [j for j in order if passes_v_gate(star, hipparcos.vmag[near[j]])]
            match.candidates = [int(hipparcos.hip[near[j]]) for j in passing]
            if not passing:
                match.reason = "V gate"
            elif len(passing) > 1:
                match.reason = "ambiguous"
            else:
                match.hip = match.candidates[0]
                match.separation_arcmin = float(separations[passing[0]])
    return matches


def double_star_designation(name: str) -> Optional[str]:
    """A name read as WDS writes a discoverer designation, or None.

    "STF 362" is "STF362", SAC's "h 4166" is "HJ4166" and "Howe 87" "HWE87".
    Catalog numbers (HD, SAO) and PiFinder's own designations are none.
    """
    match = _DESIGNATION_RE.fullmatch(name.strip())
    if match is None:
        return None
    prefix = match.group(1)
    spelled = DISCOVERER_SPELLINGS.get(prefix, prefix.upper())
    if spelled in _NOT_DISCOVERERS:
        return None
    return f"{spelled}{int(match.group(2))}"


def apply_vetoes(
    stars: Mapping[int, StarObject],
    matches: Dict[int, Match],
    hipparcos: Hipparcos,
) -> None:
    """Undo a match that contradicts the listing's own designations.

    The listing's HD, BD, CD and CPD numbers must include one of the matched
    star's, unless it has none. And a double-star designation that a WDS
    listing within VETO_RADIUS_ARCMIN carries must not place the pair
    elsewhere: that WDS listing may not match another star, nor lie more than
    WDS_PAIR_SLACK_ARCMIN from the matched one.
    """
    wds: Dict[str, List[StarObject]] = defaultdict(list)
    for star in stars.values():
        if star.catalog_code == "WDS":
            for name in star.names:
                designation = re.sub(r"\s+", "", name).upper()
                wds[designation].append(star)
    for object_id, match in matches.items():
        star = stars[object_id]
        if match.hip is None or star.catalog_code == "WDS":
            continue
        reason = _contradiction(star, match.hip, wds, matches, hipparcos)
        if reason:
            match.hip, match.separation_arcmin, match.reason = None, None, reason


def _contradiction(
    star: StarObject,
    hip: int,
    wds: Mapping[str, List[StarObject]],
    matches: Mapping[int, Match],
    hipparcos: Hipparcos,
) -> Optional[str]:
    numbers = [number for name in star.names for number in catalog_numbers(name)]
    if numbers and not any(n in hipparcos.numbers_of.get(hip, set()) for n in numbers):
        for number in numbers:
            other = hipparcos.star_with.get(number)
            if other is not None:
                return f"{' '.join(map(str, number))} is HIP {other}"
        return f"{' '.join(map(str, numbers[0]))} is no Hipparcos star's"
    index = hipparcos.index_of(hip)
    assert index is not None
    matched = unit_vectors(
        hipparcos.ra[index : index + 1], hipparcos.dec[index : index + 1]
    )[0]
    here = unit_vectors(np.array([star.ra]), np.array([star.dec]))[0]
    for name in star.names:
        designation = double_star_designation(name)
        if designation is None:
            continue
        for pair in wds.get(designation, ()):
            there = unit_vectors(np.array([pair.ra]), np.array([pair.dec]))[0]
            if (
                _arcmin(np.array([np.linalg.norm(there - here)]))[0]
                > VETO_RADIUS_ARCMIN
            ):
                continue
            pair_hip = matches[pair.object_id].hip
            if pair_hip is not None and pair_hip != hip:
                return f"WDS {name} is HIP {pair_hip}"
            away = _arcmin(np.array([np.linalg.norm(there - matched)]))[0]
            if away > WDS_PAIR_SLACK_ARCMIN:
                return f"WDS {name} is {away:.1f}' from HIP {hip}"
    return None


def apply_hip_identifications(
    cursor: sqlite3.Cursor,
    stars: Mapping[int, StarObject],
    matches: Dict[int, Match],
    identifications: Mapping[str, int],
    hipparcos: Hipparcos,
) -> None:
    """Put each `hip` correction's number in place of its listing's match.

    Fails, before anything is written, on a designator that resolves to
    nothing or to no star listing, on a HIP number Hipparcos lacks, on two
    corrections that reach one sky object, and on a correction the
    cross-match alone makes: it is redundant (ADR 0046).
    """
    problems: List[str] = []
    corrected: Dict[int, str] = {}
    for designator, hip in sorted(identifications.items()):
        label = f"hip correction for {designator}"
        try:
            code, sequence = parse_designator(designator)
        except ValueError as error:
            problems.append(f"{label}: {error}")
            continue
        listing, why_not = resolve_listing(cursor, (code, sequence))
        if listing is None:
            problems.append(f"{label}: {why_not}")
            continue
        object_id = listing["object_id"]
        if code not in STAR_CATALOGS or object_id not in stars:
            problems.append(f"{label}: {designator} is no star catalog's listing")
            continue
        if hipparcos.index_of(hip) is None:
            problems.append(f"{label}: Hipparcos has no HIP {hip}")
            continue
        if object_id in corrected:
            problems.append(
                f"{label}: conflicts with the hip correction for"
                f" {corrected[object_id]}: both identify one sky object"
            )
            continue
        corrected[object_id] = designator
        if matches[object_id].hip == hip:
            problems.append(
                f"{label}: the cross-match alone finds HIP {hip}, so the"
                " correction is redundant; delete it"
            )
            continue
        matches[object_id] = Match(object_id, hip=hip, by_correction=True)
    if problems:
        raise CorrectionError(problems)


def d_star_type(members: Sequence[StarObject]) -> str:
    """The D* rule for a star: D* if any listing's catalog types it D*.

    Each loader types its listings by the rule from its own catalog: SAC's
    doubles (less its rejected pairs) and RASC's are D*, a WDS listing is D*
    if one of its pairs is a double star, and the bright stars, SAC's red
    stars and TLK's variables are single.
    """
    return "D*" if any(member.obj_type == "D*" for member in members) else "*"


@dataclass
class StarIdentity:
    """What the stage did: each surviving sky object's HIP, and the evidence."""

    hips: Dict[int, int]
    matches: Dict[int, Match]
    stars: Dict[int, StarObject]
    # Each merged sky object's id, mapped to the survivor's.
    merged_into: Dict[int, int]


def identify_stars(
    db: ObjectsDatabase,
    hip_identifications: Mapping[str, int],
    hipparcos: Optional[Hipparcos] = None,
) -> StarIdentity:
    """Cross-match the star sky objects to Hipparcos and merge them by HIP.

    The sky objects that match one HIP number become one: the first loader's
    survives (the lowest id), as when a later loader's listing joins it, and
    keeps its position. The others' listings and names move onto it,
    in id order, their names after its own; an empty magnitude or size is
    filled by the loaders' precedence and never replaced. Each merged star is
    then typed by the D* rule. All or nothing: a problem rolls it back.
    """
    hipparcos = hipparcos if hipparcos is not None else load_hipparcos()
    conn = db.conn
    cursor = conn.cursor()
    stars = read_star_objects(cursor)
    matches = cross_match(stars, hipparcos)
    apply_vetoes(stars, matches, hipparcos)
    apply_hip_identifications(cursor, stars, matches, hip_identifications, hipparcos)

    by_hip: Dict[int, List[int]] = defaultdict(list)
    for object_id in sorted(matches):
        hip = matches[object_id].hip
        if hip is not None:
            by_hip[hip].append(object_id)

    hips: Dict[int, int] = {}
    merged_into: Dict[int, int] = {}
    try:
        for hip, members in sorted(by_hip.items(), key=lambda item: item[1][0]):
            survivor, others = members[0], members[1:]
            hips[survivor] = hip
            for other in others:
                star = stars[other]
                fill_sky_object(conn, survivor, star.catalog_code, star.mag, star.size)
                merge_sky_object(cursor, other, survivor)
                merged_into[other] = survivor
            obj_type = d_star_type([stars[member] for member in members])
            if obj_type != stars[survivor].obj_type:
                cursor.execute(
                    "UPDATE objects SET obj_type = ? WHERE id = ?",
                    (obj_type, survivor),
                )
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    _log_summary(stars, matches, merged_into, hip_identifications)
    return StarIdentity(hips, matches, stars, merged_into)


def _log_summary(
    stars: Mapping[int, StarObject],
    matches: Mapping[int, Match],
    merged_into: Mapping[int, int],
    hip_identifications: Mapping[str, int],
) -> None:
    matched: Counter = Counter()
    total: Counter = Counter()
    for object_id, star in stars.items():
        total[star.catalog_code] += 1
        if matches[object_id].hip is not None:
            matched[star.catalog_code] += 1
    for code in STAR_CATALOGS:
        if total[code]:
            logging.info(
                "Star identity: %s matches %d of %d sky objects to Hipparcos",
                code,
                matched[code],
                total[code],
            )
    reasons = Counter(
        "veto" if " is " in match.reason else match.reason
        for match in matches.values()
        if match.reason
    )
    logging.info(
        "Star identity: merged %d sky objects into %d stars, %d by hip"
        " correction; no match: %s",
        len(merged_into),
        len(set(merged_into.values())),
        len(hip_identifications),
        ", ".join(f"{reason} {count}" for reason, count in sorted(reasons.items())),
    )
