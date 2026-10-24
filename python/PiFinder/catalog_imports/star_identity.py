"""
Star identity: a star is identified by its Hipparcos number.

The star catalogs (Str, SaM, SaR, TLK, RDS, WDS) list many of the same stars,
and few of their listings carry a designation the loaders' lookup resolves, so
each loader leaves a star a sky object of its own: Mizar was SaM's and Str's.
This stage cross-matches each star sky object to hip_main.dat and merges the
sky objects that match one HIP number into one, typed by the D* rule
(docs/ax/catalog.md §9.3). It runs after post-processing and before the
supplementary sources and the correction pass (§9.1).

A `hip` correction names the Hipparcos number of a listing whose source
position or magnitude is too wrong to match (ADR 0046, decision 4). This stage
reads them before it cross-matches and uses each in place of position.
"""

import logging
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
from .catalog_import_utils import ROUNDED_POSITIONS, fill_sky_object, merge_sky_object
from .corrections import CorrectionError, parse_designator, resolve_listing

# The catalogs whose listings are stars, in loader order.
STAR_CATALOGS = ("SaM", "SaR", "Str", "RDS", "TLK", "WDS")

# The match radius follows the precision of a listing's position. SAC, RASC
# and the bright stars round to 0.1m in RA and 1' in Dec, so their stars lie
# up to 2-3' from Hipparcos's. WDS and TLK give arcseconds, and a WDS pair
# that lies more than 0.5' from the nearest Hipparcos star is nearly always
# another star (catalog.md §9.3); a WDS row without arcsecond coordinates is
# placed by its identifier, rounded (ROUNDED_POSITIONS).
MATCH_RADIUS_ARCMIN = 3.0
PRECISE_MATCH_RADIUS_ARCMIN = 0.5
PRECISE_CATALOGS = frozenset({"WDS", "TLK"})

# The V gate: a listing's V must lie within this of the Hipparcos star's, or
# for a variable listed by its range (TLK's [max, min]), the Hipparcos star's
# V within this of the range.
V_TOLERANCE = 1.0
RANGE_CATALOGS = frozenset({"TLK"})
# A variable matches by position alone when no star passes the V gate. TLK's
# ranges are often photographic (La Superba's 7.4-10.0 is 4.9-7.3 in V), and
# the catalogs give a large-amplitude variable its maximum where Hipparcos
# gives its mean (Mira: SAC 2.0, Hipparcos 6.47). Hipparcos flags an
# amplitude over 0.6 mag 3.
LARGE_AMPLITUDE_FLAG = 3

# Hipparcos positions are for J1991.25; the sources give J2000.
HIPPARCOS_EPOCH = 1991.25
SOURCE_EPOCH = 2000.0
_MAS_PER_DEGREE = 3.6e6

# The fields of hip_main.dat this stage reads, by position (VizieR I/239):
# H1 the HIP number, H3/H4 the position in h m s and d m s, H5 V, H6 the
# variability flag, H8/H9 the position in degrees (blank for the 263 stars
# with no astrometric solution, such as ξ UMa) and H12/H13 the proper motion
# in mas/yr, the RA component times cos(Dec).
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
}


@dataclass
class Hipparcos:
    """The Hipparcos stars, at J2000 by their proper motion."""

    hip: np.ndarray
    ra: np.ndarray
    dec: np.ndarray
    vmag: np.ndarray
    var_flag: np.ndarray
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


def load_hipparcos(path: Optional[Path] = None) -> Hipparcos:
    """Read hip_main.dat, with each position carried to J2000."""
    path = path or Path(utils.astro_data_dir, "hip_main.dat")
    frame = pd.read_csv(
        path,
        sep="|",
        header=None,
        usecols=list(_HIP_FIELDS),
        skipinitialspace=True,
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
    return Hipparcos(
        hip=frame["hip"].to_numpy(dtype=int),
        ra=np.mod(ra_2000, 360),
        dec=dec_2000,
        vmag=frame["vmag"].to_numpy(dtype=float),
        var_flag=np.nan_to_num(frame["var_flag"].to_numpy(dtype=float)).astype(int),
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
    # Whether its position is to the arcsecond (WDS's and TLK's, but for a
    # WDS row placed by its identifier).
    precise: bool = False
    listings: List[str] = field(default_factory=list)

    @property
    def vmag(self) -> Optional[float]:
        """The V the gate compares: the first magnitude, the primary's."""
        mags = self.numeric_mags
        return mags[0] if mags else None

    @property
    def numeric_mags(self) -> List[float]:
        return [float(m) for m in self.mag.mags if utils.is_number(m)]

    @property
    def radius_arcmin(self) -> float:
        return PRECISE_MATCH_RADIUS_ARCMIN if self.precise else MATCH_RADIUS_ARCMIN


def read_star_objects(
    cursor: sqlite3.Cursor, rounded: Optional[Set[Tuple[str, int]]] = None
) -> Dict[int, StarObject]:
    """Every sky object with a star catalog's listing, by object id.

    `rounded` names the listings of a precise catalog whose position is
    rounded; it defaults to what the loaders recorded in ROUNDED_POSITIONS.
    """
    rounded = ROUNDED_POSITIONS if rounded is None else rounded
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
                precise=(
                    row["catalog_code"] in PRECISE_CATALOGS and listing not in rounded
                ),
            )
        star.listings.append(f"{row['catalog_code']} {row['sequence']}")
    return stars


@dataclass
class Match:
    """A star sky object's Hipparcos star, or why it has none."""

    object_id: int
    hip: Optional[int] = None
    separation_arcmin: Optional[float] = None
    # How many Hipparcos stars within the radius could have matched: those
    # that pass the V gate or, failing any, the variables.
    candidates: int = 0
    # The nearest Hipparcos star within the radius that failed the V gate,
    # as (HIP, separation in arcmin, its V), where it came first.
    rejected_by_v: Optional[Tuple[int, float, float]] = None
    by_correction: bool = False


def passes_v_gate(star: StarObject, hip_vmag: float) -> bool:
    """Whether a listing's V agrees with a Hipparcos star's (V_TOLERANCE).

    A variable listed by its range passes when the Hipparcos star's V lies
    within V_TOLERANCE of the range. A listing without a V, or a Hipparcos
    star without one, passes: it is matched by position alone.
    """
    mags = star.numeric_mags
    if not mags or np.isnan(hip_vmag):
        return True
    if star.catalog_code in RANGE_CATALOGS:
        low, high = min(mags), max(mags)
    else:
        low = high = mags[0]
    return low - V_TOLERANCE <= hip_vmag <= high + V_TOLERANCE


def matches_as_variable(star: StarObject, var_flag: int) -> bool:
    """Whether a Hipparcos star may match a listing whose V it fails.

    A variable's V is not compared: TLK's variables, and Hipparcos's
    large-amplitude ones. Such a star matches only when no star within the
    radius passes the V gate, so a variable never takes a listing from the
    star its V describes (STF 2816, beside the variable HIP 106890).
    """
    return star.catalog_code in RANGE_CATALOGS or var_flag == LARGE_AMPLITUDE_FLAG


def cross_match(
    stars: Mapping[int, StarObject],
    hipparcos: Hipparcos,
    radius_scale: float = 1.0,
) -> Dict[int, Match]:
    """Each star sky object's Hipparcos star: the nearest within its radius
    that passes the V gate, or failing that the nearest variable.
    `radius_scale` widens every radius, to see what lies just outside it."""
    stars_list = list(stars.values())
    matches: Dict[int, Match] = {}
    if not stars_list:
        return matches
    vectors = unit_vectors(
        np.array([star.ra for star in stars_list]),
        np.array([star.dec for star in stars_list]),
    )
    radii = np.array([star.radius_arcmin * radius_scale for star in stars_list])
    for radius in np.unique(radii):
        chosen = np.flatnonzero(radii == radius)
        found = hipparcos.tree.query_ball_point(vectors[chosen], _chord(radius))
        for i, candidates in zip(chosen, found):
            star = stars_list[i]
            match = matches[star.object_id] = Match(star.object_id)
            if not candidates:
                continue
            candidates = np.array(candidates)
            separations = _arcmin(
                np.linalg.norm(hipparcos.tree.data[candidates] - vectors[i], axis=1)
            )
            # Nearest first; ties fall to the lower HIP, so every import picks
            # the same star.
            order = np.lexsort((hipparcos.hip[candidates], separations))
            passing = [
                j for j in order if passes_v_gate(star, hipparcos.vmag[candidates[j]])
            ] or [
                j
                for j in order
                if matches_as_variable(star, hipparcos.var_flag[candidates[j]])
            ]
            nearest = candidates[order[0]]
            if not passing or passing[0] != order[0]:
                match.rejected_by_v = (
                    int(hipparcos.hip[nearest]),
                    float(separations[order[0]]),
                    float(hipparcos.vmag[nearest]),
                )
            if passing:
                best = passing[0]
                match.hip = int(hipparcos.hip[candidates[best]])
                match.separation_arcmin = float(separations[best])
                match.candidates = len(passing)
    return matches


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
    logging.info(
        "Star identity: merged %d sky objects into %d stars, %d by hip"
        " correction; the V gate turned away %d nearest stars",
        len(merged_into),
        len(set(merged_into.values())),
        len(hip_identifications),
        sum(match.rejected_by_v is not None for match in matches.values()),
    )
