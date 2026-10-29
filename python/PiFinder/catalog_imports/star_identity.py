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
from .catalog_import_utils import (
    SAC_SYSTEMS,
    SOURCE_DM_NUMBERS,
    STAND_IN_POSITIONS,
    fill_sky_object,
    merge_sky_object,
)
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
# Exact identifiers, for a star the position match leaves unmatched (catalog.md
# §9.3): a catalog number the star shares with Hipparcos's own columns, a WDS
# designation it shares with a matched WDS listing, and SAC's own grouping of
# a multiple star's rows. A shared identifier is right when it fires, but a
# source's number can be a slip, so the star a number names must also lie
# within this distance of the listing: 3' for a rounded position, 30" for an
# arcsecond one (WDS's DM column names stars 1-3' away that its V does not
# fit).
IDENTIFIER_RADIUS_ARCMIN = 3.0
PRECISE_IDENTIFIER_RADIUS_ARCMIN = 0.5

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
    _by_dm: Optional[Dict[Tuple[str, int, int], Set[int]]] = field(
        default=None, init=False, repr=False
    )
    _index: Optional[Dict[int, int]] = field(default=None, init=False, repr=False)

    @property
    def tree(self) -> cKDTree:
        if self._tree is None:
            self._tree = cKDTree(unit_vectors(self.ra, self.dec))
        return self._tree

    def stars_with_dm(self, dm: Tuple[str, int, int]) -> Set[int]:
        """The stars whose BD, CD or CPD number is (sign, zone, number)."""
        if self._by_dm is None:
            self._by_dm = defaultdict(set)
            for number, keys in self.numbers_of.items():
                for key in keys:
                    if key[0] != "HD":
                        self._by_dm[key[1:]].add(number)
        return self._by_dm.get(dm, set())

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
    # The DM number its source gives outside its names (WDS's), and for a SAC
    # continuation row, its system's first listing.
    dm: Optional[Tuple[str, int, int]] = None
    system_first: Optional[Tuple[str, int]] = None

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
    cursor: sqlite3.Cursor,
    stand_in: Optional[Set[Tuple[str, int]]] = None,
    dm_numbers: Optional[Mapping[Tuple[str, int], Tuple[str, int, int]]] = None,
    systems: Optional[Mapping[Tuple[str, int], Tuple[str, int]]] = None,
) -> Dict[int, StarObject]:
    """Every sky object with a star catalog's listing, by object id.

    `stand_in`, `dm_numbers` and `systems` default to what the loaders
    recorded in STAND_IN_POSITIONS, SOURCE_DM_NUMBERS and SAC_SYSTEMS.
    """
    stand_in = STAND_IN_POSITIONS if stand_in is None else stand_in
    dm_numbers = SOURCE_DM_NUMBERS if dm_numbers is None else dm_numbers
    systems = SAC_SYSTEMS if systems is None else systems
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
                dm=dm_numbers.get(listing),
                system_first=systems.get(listing),
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
    # The rule that made it: "position", "catalog number", "WDS designation"
    # or "SAC system".
    rule: Optional[str] = None
    # A SAC continuation row joins its system's first row's sky object,
    # with that row's HIP, or none.
    joined_to: Optional[int] = None
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
                match.rule = "position"
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
    wds = _wds_index(stars)
    for object_id, match in matches.items():
        star = stars[object_id]
        if match.hip is None or star.catalog_code == "WDS":
            continue
        reason = _contradiction(star, match.hip, wds, matches, hipparcos)
        if reason:
            match.hip, match.separation_arcmin, match.reason = None, None, reason
            match.rule = None


def _wds_index(stars: Mapping[int, StarObject]) -> Dict[str, List[StarObject]]:
    """The WDS listings, by each designation they carry ("STF1744")."""
    wds: Dict[str, List[StarObject]] = defaultdict(list)
    for star in stars.values():
        if star.catalog_code == "WDS":
            for name in star.names:
                wds[re.sub(r"\s+", "", name).upper()].append(star)
    return wds


def _separation_arcmin(star: StarObject, ra: float, dec: float) -> float:
    here = unit_vectors(np.array([star.ra]), np.array([star.dec]))[0]
    there = unit_vectors(np.array([ra]), np.array([dec]))[0]
    return float(_arcmin(np.array([np.linalg.norm(there - here)]))[0])


def _hip_separation(star: StarObject, hip: int, hipparcos: Hipparcos) -> float:
    index = hipparcos.index_of(hip)
    assert index is not None
    return _separation_arcmin(star, hipparcos.ra[index], hipparcos.dec[index])


def number_candidates(star: StarObject, hipparcos: Hipparcos) -> Set[int]:
    """Rule 1: the Hipparcos stars the listing's catalog numbers name.

    An HD, BD, CD or CPD number in its names must be the star's in that
    column; WDS's DM column, which does not say which Durchmusterung it is,
    may be in any of the three. A named star beyond the identifier radius is
    taken for a slip in the source (TU Gem's HD 42247 names a star 65° away).
    A number never overrides an arcsecond position: for WDS and TLK the named
    star must also be the nearest Hipparcos star (θ¹ Ori's PTR 1 sits on HIP
    26220 while its DM names HIP 26221, 13" away).
    """
    radius = (
        PRECISE_IDENTIFIER_RADIUS_ARCMIN if star.precise else IDENTIFIER_RADIUS_ARCMIN
    )
    named = {
        hipparcos.star_with[number]
        for name in star.names
        for number in catalog_numbers(name)
        if number in hipparcos.star_with
    }
    if star.dm is not None:
        named |= hipparcos.stars_with_dm(star.dm)
    named = {h for h in named if _hip_separation(star, h, hipparcos) <= radius}
    if named and star.precise:
        here = unit_vectors(np.array([star.ra]), np.array([star.dec]))[0]
        _, nearest = hipparcos.tree.query(here)
        named &= {int(hipparcos.hip[nearest])}
    return named


def designation_candidates(
    star: StarObject,
    wds: Mapping[str, List[StarObject]],
    matches: Mapping[int, Match],
    hipparcos: Hipparcos,
) -> Set[int]:
    """Rule 2: the stars of the matched WDS listings that carry the
    listing's own double-star designation, within VETO_RADIUS_ARCMIN.

    A designation names a pair, not one of its stars, so the star must pass
    the listing's V gate where the listing gives a V (θ¹ Ori's 5.1 is C, not
    the WDS primary of STF 748). And a WDS listing whose own DM names another
    star than its match vouches for nothing: which of a near-equal pair is
    its primary is not settled (STF 1122).
    """
    found: Set[int] = set()
    for name in star.names:
        designation = double_star_designation(name)
        for pair in wds.get(designation or "", ()):
            hip = matches[pair.object_id].hip
            if (
                hip is None
                or _separation_arcmin(star, pair.ra, pair.dec) > VETO_RADIUS_ARCMIN
            ):
                continue
            dm_stars = {
                h
                for h in (hipparcos.stars_with_dm(pair.dm) if pair.dm else ())
                if _hip_separation(pair, h, hipparcos) <= VETO_RADIUS_ARCMIN
            }
            if dm_stars and hip not in dm_stars:
                continue
            index = hipparcos.index_of(hip)
            assert index is not None
            if star.vmag is not None and not passes_v_gate(star, hipparcos.vmag[index]):
                continue
            found.add(hip)
    return found


def apply_identifier_rules(
    stars: Mapping[int, StarObject],
    matches: Dict[int, Match],
    hipparcos: Hipparcos,
) -> None:
    """Identify the stars the position match left unmatched by an identifier.

    A rule never replaces a position match. Rule 1 (catalog numbers) runs
    first, so that a WDS listing it identifies counts for rule 2 (WDS
    designations); rule 3 (SAC systems) joins a continuation row to its
    system's first row. Two rules naming different stars, one rule naming
    two, or a veto against the result (apply_vetoes): no match.
    """
    unmatched = [oid for oid, match in sorted(matches.items()) if match.hip is None]
    wds = _wds_index(stars)
    proposals: Dict[int, Dict[str, Set[int]]] = {
        oid: {"catalog number": number_candidates(stars[oid], hipparcos)}
        for oid in unmatched
    }
    for oid in unmatched:
        if stars[oid].catalog_code == "WDS":
            _decide(stars[oid], matches[oid], proposals[oid], wds, matches, hipparcos)
    for oid in unmatched:
        star = stars[oid]
        if star.catalog_code != "WDS":
            proposals[oid]["WDS designation"] = designation_candidates(
                star, wds, matches, hipparcos
            )
            if star.system_first is None:
                _decide(star, matches[oid], proposals[oid], wds, matches, hipparcos)
    by_listing = {star.listings[0]: oid for oid, star in stars.items()}
    for oid in unmatched:
        star = stars[oid]
        if star.system_first is None:
            continue
        first = by_listing.get(f"{star.system_first[0]} {star.system_first[1]}")
        if first is None:
            continue
        match = matches[oid]
        own = set().union(*proposals[oid].values())
        system_hip = matches[first].hip
        if own and own != {system_hip}:
            match.reason = "rules disagree: its own identifiers name another star"
            continue
        if system_hip is not None:
            reason = _contradiction(star, system_hip, wds, matches, hipparcos)
            if reason:
                match.reason = reason
                continue
        match.joined_to, match.rule, match.reason = first, "SAC system", None
        match.hip = system_hip


def _decide(
    star: StarObject,
    match: Match,
    proposal: Mapping[str, Set[int]],
    wds: Mapping[str, List[StarObject]],
    matches: Mapping[int, Match],
    hipparcos: Hipparcos,
) -> None:
    named = {rule: hips for rule, hips in proposal.items() if hips}
    if not named:
        return
    hips = set().union(*named.values())
    if len(hips) > 1:
        match.reason = "rules disagree: " + ", ".join(
            f"{rule} names HIP {', '.join(map(str, sorted(h)))}"
            for rule, h in named.items()
        )
        return
    (hip,) = hips
    if star.catalog_code != "WDS":
        reason = _contradiction(star, hip, wds, matches, hipparcos)
        if reason:
            match.reason = reason
            return
    match.hip, match.reason = hip, None
    match.rule = " and ".join(sorted(named))
    match.separation_arcmin = _hip_separation(star, hip, hipparcos)


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
    apply_identifier_rules(stars, matches, hipparcos)
    apply_hip_identifications(cursor, stars, matches, hip_identifications, hipparcos)
    # A joined continuation row follows its system's first row, which a hip
    # correction may have identified since.
    for match in matches.values():
        if match.joined_to is not None:
            match.hip = matches[match.joined_to].hip

    hips: Dict[int, int] = {}
    merged_into: Dict[int, int] = {}
    try:
        for members, hip in _star_groups(matches):
            survivor, others = members[0], members[1:]
            if hip is not None:
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


def _star_groups(
    matches: Mapping[int, Match],
) -> List[Tuple[List[int], Optional[int]]]:
    """The sky objects that become one, each group with its HIP (or None).

    Those matched to one HIP number are one star, and a SAC continuation row
    joins its system's first row, matched or not. Groups and their members
    come in id order.
    """
    parent: Dict[int, int] = {}

    def root(oid: int) -> int:
        while parent.setdefault(oid, oid) != oid:
            oid = parent[oid]
        return oid

    def join(a: int, b: int) -> None:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    first_of_hip: Dict[int, int] = {}
    for oid in sorted(matches):
        match = matches[oid]
        if match.hip is not None:
            join(oid, first_of_hip.setdefault(match.hip, oid))
        if match.joined_to is not None:
            join(oid, match.joined_to)
    members: Dict[int, List[int]] = defaultdict(list)
    for oid in sorted(parent):
        members[root(oid)].append(oid)
    groups = []
    for _, group in sorted(members.items()):
        hips = sorted({h for h in (matches[oid].hip for oid in group) if h is not None})
        assert len(hips) <= 1, f"sky objects {group} would join HIPs {hips}"
        groups.append((group, hips[0] if hips else None))
    return groups


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
    rules = Counter(match.rule for match in matches.values() if match.rule)
    logging.info(
        "Star identity: matched by %s",
        ", ".join(f"{rule} {count}" for rule, count in sorted(rules.items())),
    )
    reasons = Counter(
        "veto"
        if " is " in match.reason
        else "rules disagree"
        if match.reason.startswith("rules disagree")
        else match.reason
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
