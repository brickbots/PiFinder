"""
Shared utilities for catalog import operations.

This module contains common classes and functions used by all catalog loaders.
"""

import logging
import math
import re
import sqlite3
from typing import Dict, List, Optional, Sequence, Tuple
from dataclasses import dataclass, field
from tqdm import tqdm

from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder import calc_utils
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.db.observations_db import ObservationsDatabase

# Global database objects (will be initialized by the main import script)
objects_db: Optional[ObjectsDatabase] = None
observations_db: Optional[ObservationsDatabase] = None

# The match guard (docs/ax/catalog.md §9.3): a listing joins the sky object an
# aka names only within this distance of it, or within the sky object's own
# size where that is larger.
MATCH_RADIUS_ARCMIN = 30.0

# Types a listing of either kind may join: an unknown type, which the guard
# can't judge, and a star group (Steinicke's *3 and *4, such as M 73), which
# cluster catalogs and double-star lists both list.
_EITHER_KIND_TYPES = frozenset({"", "?", "-", "***"})

# Star types as the loaders write them, before fix_object_types normalises
# them: "*" (or "* "), "D*" and "**", each perhaps with a trailing "?".
_STAR_TYPE_RE = re.compile(r"(\*\*?|D\*)\??")

# Precedence (docs/ax/catalog.md §9.1): a listing that joins a sky object an
# earlier loader created fills an empty magnitude or size and replaces nothing,
# but for these exceptions, keyed by the joining listing's catalog code. A new
# exception belongs in that table and here, never in a loader.
#
# Harris is the reference for Milky Way globulars, and every Harris listing is
# one: its magnitude replaces the sky object's.
MAGNITUDE_REPLACED_BY = frozenset({"Har"})
# A cluster on PiFinder's globular list is a globular.
TYPE_SET_BY = {"EGC": "Gb"}


@dataclass
class MatchRejection:
    """A join the match guard refused: the listing became its own sky object."""

    listing: str
    aka: str
    object_id: int
    reason: str


# Every rejection in this import, in order. Rejections don't fail the import.
MATCH_REJECTIONS: List[MatchRejection] = []


def separation_arcmin(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle distance between two positions in degrees, in arcminutes."""
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1, dec1, ra2, dec2))
    # Haversine: stays accurate for the sub-arcminute separations of a match.
    h = (
        math.sin((dec2 - dec1) / 2) ** 2
        + math.cos(dec1) * math.cos(dec2) * math.sin((ra2 - ra1) / 2) ** 2
    )
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h)))) * 60


def is_star_type(obj_type: Optional[str]) -> Optional[bool]:
    """Whether a type is a star's, or None when it is compatible with both kinds."""
    cleaned = (obj_type or "").strip()
    if cleaned in _EITHER_KIND_TYPES:
        return None
    return _STAR_TYPE_RE.fullmatch(cleaned) is not None


def match_guard(
    obj_type: str, ra: float, dec: float, sky_object: sqlite3.Row
) -> Optional[str]:
    """Why a listing may not join a sky object, or None if it may.

    The types must be compatible: a star joins only a star, and anything else
    only a non-star; an unknown type ("?") and a star group ("***") are
    compatible with both. And the listing must lie within MATCH_RADIUS_ARCMIN
    of the sky object, or within the sky object's major axis where that is
    larger.
    """
    listing_is_star = is_star_type(obj_type)
    object_is_star = is_star_type(sky_object["obj_type"])
    if (
        listing_is_star is not None
        and object_is_star is not None
        and listing_is_star != object_is_star
    ):
        return f"types {obj_type.strip()} and {sky_object['obj_type'].strip()}"
    separation = separation_arcmin(ra, dec, sky_object["ra"], sky_object["dec"])
    major_axis = SizeObject.from_json(sky_object["size"]).max_extent_arcsec / 60
    limit = max(MATCH_RADIUS_ARCMIN, major_axis)
    if separation > limit:
        return f"{separation:.1f}' apart, limit {limit:.0f}'"
    return None


@dataclass
class NewCatalogObject:
    object_type: str
    catalog_code: str
    sequence: int
    ra: float
    dec: float
    mag: MagnitudeObject
    object_id: int = 0
    size: SizeObject = field(default_factory=lambda: SizeObject([]))
    description: str = ""
    aka_names: list[str] = field(default_factory=list)
    surface_brightness: float = 0.0
    # Read lettered akas ("NGC 4676A") as components: see ObjectFinder.resolve.
    # Only the Arp loader sets it.
    lettered_components: bool = False

    # Class-level shared finder for performance optimization
    _shared_finder: Optional["ObjectFinder"] = None

    @classmethod
    def set_shared_finder(cls, finder: "ObjectFinder") -> None:
        """Set a shared ObjectFinder instance for all objects to use during bulk operations"""
        cls._shared_finder = finder

    @classmethod
    def clear_shared_finder(cls) -> None:
        """Clear the shared ObjectFinder instance"""
        cls._shared_finder = None

    def insert(self, find_object_id=True):
        """
        Inserts object into DB
        """
        # sanity checks
        if type(self.aka_names) is not list:
            raise TypeError("Aka names not list")

        # Check to see if this object matches one in the DB already
        # This is a costly operation, so disabled for 'source' catalogs like WDS
        finder = None
        if find_object_id:
            finder = self.__class__._shared_finder or ObjectFinder()
            self.find_object_id(finder)
        joined = self.object_id != 0

        try:
            # Enable bulk mode to prevent individual commits
            objects_db.bulk_mode = True
            objects_db.conn.execute("BEGIN TRANSACTION")

            if joined:
                self.fill_joined_object(group=self.describes_a_group(finder))
            else:
                # Did not find a match, first insert object info
                self.find_constellation()
                assert isinstance(self.mag, MagnitudeObject)

                self.object_id = objects_db.insert_object(
                    self.object_type,
                    self.ra,
                    self.dec,
                    self.constellation,
                    self.size.to_json(),
                    self.mag.to_json(),
                    self.surface_brightness,
                )

            # By the time we get here, we have an object_id
            objects_db.insert_catalog_object(
                self.object_id, self.catalog_code, self.sequence, self.description
            )

            # now the names
            # First, catalog name
            objects_db.insert_name(
                self.object_id,
                f"{self.catalog_code} {self.sequence}",
                self.catalog_code,
            )
            for aka in self.aka_names:
                if finder is None or self.keeps_as_name(aka, finder, joined):
                    objects_db.insert_name(self.object_id, aka, self.catalog_code)
                else:
                    logging.debug(
                        "Not naming %s %s %r: another sky object's designation",
                        self.catalog_code,
                        self.sequence,
                        aka,
                    )

            # Commit the transaction
            objects_db.conn.commit()

        except Exception as e:
            objects_db.conn.rollback()
            logging.error(f"Database error inserting object: {e}")
            raise
        finally:
            # Restore bulk mode to False
            objects_db.bulk_mode = False

    def keeps_as_name(self, aka: str, finder: "ObjectFinder", joined: bool) -> bool:
        """Whether an aka is stored as one of this listing's names.

        A designation of a PiFinder catalog is a name only of the sky object it
        resolves to, so a member's number (NGC 869 in the Double Cluster's
        "869;884") is not stored on its sibling. One that resolves to nothing
        names something PiFinder doesn't hold: on a joined sky object that is
        another object (NGC 1097A beside NGC 1097), but a listing of its own
        may carry it (Arp 79 is NGC 5490C). Every other aka, a common name or
        another catalog's number, is stored.
        """
        is_designation, object_id = finder.resolve(
            aka, self.aka_names, self.lettered_components
        )
        if not is_designation:
            return True
        if object_id is None:
            return not joined
        return object_id == self.object_id

    def describes_a_group(self, finder: Optional["ObjectFinder"]) -> bool:
        """Whether this listing's akas resolve to more than one sky object.

        Such a listing gives the group's values, not those of the member it
        joins: TAAS's "2237;2244" carries NGC 2244's cluster magnitude, which
        is no value of NGC 2237, the Rosette Nebula.
        """
        if finder is None:
            return False
        named = {
            finder.resolve(aka, self.aka_names, self.lettered_components)[1]
            for aka in self.aka_names
        }
        named.discard(None)
        return len(named) > 1

    def fill_joined_object(self, group: bool = False):
        """Fill the joined sky object's empty values from this listing.

        A later loader fills an empty magnitude or size and never replaces a
        value; the type and position are the first loader's. A listing that
        describes a group fills nothing. The exceptions are
        MAGNITUDE_REPLACED_BY and TYPE_SET_BY (docs/ax/catalog.md §9.1).
        """
        assert objects_db is not None
        sky_object = objects_db.conn.execute(
            "SELECT obj_type, mag, size FROM objects WHERE id = ?", (self.object_id,)
        ).fetchone()
        updates = {}
        has_mag = self.mag.filter_mag != MagnitudeObject.UNKNOWN_MAG
        object_mag = MagnitudeObject.from_json(sky_object["mag"])
        fills = not group
        if has_mag and (
            (fills and object_mag.filter_mag == MagnitudeObject.UNKNOWN_MAG)
            or self.catalog_code in MAGNITUDE_REPLACED_BY
        ):
            updates["mag"] = self.mag.to_json()
        object_size = SizeObject.from_json(sky_object["size"])
        if fills and self.size.extents and not object_size.extents:
            updates["size"] = self.size.to_json()
        obj_type = TYPE_SET_BY.get(self.catalog_code)
        if obj_type is not None and sky_object["obj_type"] != obj_type:
            updates["obj_type"] = obj_type
        if not updates:
            return
        logging.debug(
            "%s %s fills %s on object %d",
            self.catalog_code,
            self.sequence,
            ", ".join(updates),
            self.object_id,
        )
        columns = ", ".join(f"{column} = ?" for column in updates)
        objects_db.conn.execute(
            f"UPDATE objects SET {columns} WHERE id = ?",
            (*updates.values(), self.object_id),
        )

    def find_constellation(self):
        """
        Uses RA/DEC to figure out what constellation this object is in
        """
        self.constellation = calc_utils.sf_utils.radec_to_constellation(
            self.ra, self.dec
        )
        if self.constellation is None:
            raise ValueError("Constellation not set")

    def find_object_id(self, finder: Optional["ObjectFinder"] = None):
        """Join the sky object of the first aka that passes the match guard.

        Each aka that resolves to a sky object is a candidate, in source order.
        match_guard rejects one of an incompatible type or too far away; every
        rejection is logged and kept in MATCH_REJECTIONS. If no candidate
        passes, object_id stays 0 and the listing becomes a sky object of its
        own.
        """
        assert objects_db is not None
        # Use class-level shared finder if available, otherwise create new one
        finder = finder or self.__class__._shared_finder or ObjectFinder()
        rejected = set()
        for aka in self.aka_names:
            _, object_id = finder.resolve(aka, self.aka_names, self.lettered_components)
            if object_id is None or object_id in rejected:
                continue
            sky_object = objects_db.conn.execute(
                "SELECT obj_type, ra, dec, size FROM objects WHERE id = ?",
                (object_id,),
            ).fetchone()
            reason = match_guard(self.object_type, self.ra, self.dec, sky_object)
            if reason is None:
                self.object_id = object_id
                return
            rejected.add(object_id)
            rejection = MatchRejection(
                f"{self.catalog_code} {self.sequence}", aka, object_id, reason
            )
            MATCH_REJECTIONS.append(rejection)
            logging.warning(
                "Match guard: %s does not join %r (object %d): %s",
                rejection.listing,
                aka,
                object_id,
                reason,
            )


# A component letter after a designation: "NGC 4676A", "M51B".
_COMPONENT_RE = re.compile(r"(.*\d)\s*([A-Za-z])")


def parse_component(raw: str) -> Optional[Tuple[str, int, str]]:
    """Split a lettered designation into catalog code, sequence and letter.

    "NGC 4676A" -> ("NGC", 4676, "A"), "M51B" -> ("M", 51, "B"). None unless
    the part before the letter is a designation parse_designation reads, so
    "UGC 10814A" and "h 2827A" are no component of anything.
    """
    match = _COMPONENT_RE.fullmatch(trim_string(raw))
    if match is None:
        return None
    parsed = parse_designation(match.group(1))
    if parsed is None:
        return None
    return parsed[0], parsed[1], match.group(2).upper()


class ObjectFinder:
    """
    Finds object id for a given catalog code and sequence number.
    Should be reinited for every catalog as the database changes.
    """

    mappings: Dict[Tuple[str, int], int]

    def __init__(self, db: Optional[ObjectsDatabase] = None):
        self.objects_db = db or ObjectsDatabase()
        self.catalog_objects = self.objects_db.get_catalog_objects()
        self.mappings = {
            (row["catalog_code"], row["sequence"]): row["object_id"]
            for row in self.catalog_objects
        }

    def resolve(
        self,
        aka: str,
        listing_akas: Sequence[str] = (),
        lettered_components: bool = False,
    ) -> Tuple[bool, Optional[int]]:
        """Whether an aka is a designation of a PiFinder catalog, and its sky object.

        listing_named reads designations, so the prefix allowlist governs
        every lookup: "B53" and "h99" are never Barnard 53 or Herschel 400
        #99. The sky object is None when the designation resolves to nothing.

        With ``lettered_components``, a lettered aka ("NGC 4676A") is a
        designation too. It resolves to the sky object of its number when it
        is the A component and the listing, ``listing_akas``, does not also
        name the number itself: PiFinder's NGC 4676 is that component, and
        Arp 242 lists only NGC 4676A and B, but Arp 77 lists both NGC 1097 and
        NGC 1097A, a companion galaxy beside it. Any other letter is a galaxy
        of its own (NGC 5490C) and resolves to nothing. A source can mean
        either by the letter, so only a loader that has checked its own opts
        in.
        """
        listing = listing_named(aka)
        if listing is not None:
            return True, self.mappings.get(listing)
        component = parse_component(aka) if lettered_components else None
        if component is None:
            return False, None
        catalog_code, sequence, letter = component
        if letter != "A" or any(
            listing_named(other) == (catalog_code, sequence) for other in listing_akas
        ):
            return True, None
        return True, self.mappings.get((catalog_code, sequence))

    def get_object_id(self, object_name: str) -> Optional[int]:
        logging.debug(f"Looking up object id for {object_name}")
        _, result = self.resolve(object_name)
        if result:
            logging.debug(f"Found object id {result} for {object_name}")
        else:
            logging.debug(f"DID NOT Find object id {result} for {object_name}")
        return result


# Trailing unit suffixes a size token may carry, mapped to their arcsecond
# multiplier. A bare token defaults to arcminutes (see parse_arcmin_size).
_SIZE_UNIT_MULTIPLIERS = {'"': 1.0, "'": 60.0, "°": 3600.0}


def _size_token_to_arcsec(token: str) -> Optional[float]:
    """Convert one size token to arcseconds, honouring a trailing unit suffix.

    ' -> arcmin, " -> arcsec, ° -> degrees; a bare number defaults to arcmin.
    Returns None when the numeric part can't be parsed.
    """
    multiplier = _SIZE_UNIT_MULTIPLIERS["'"]  # bare tokens are arcminutes
    if token and token[-1] in _SIZE_UNIT_MULTIPLIERS:
        multiplier = _SIZE_UNIT_MULTIPLIERS[token[-1]]
        token = token[:-1]
    try:
        return float(token) * multiplier
    except ValueError:
        return None


def parse_arcmin_size(raw: str, strict: bool = False) -> SizeObject:
    """Parse a size string into a SizeObject (extents stored in arcseconds).

    Values default to arcminutes, but a token may override its unit with a
    trailing suffix: ' (arcmin), " (arcsec), or ° (degrees) — so arcsecond
    catalogs like EGC ('36"') parse correctly. The axis separators 'x', '×',
    '/', and '+' are all treated as delimiters, so "32'x6.5'", "0.3/5.8", and
    "30'+30'" each yield two extents. Two extents are an ellipse's axes, and
    SizeObject keeps the major axis first, so Collinder's "25x30" is
    30' x 25'. Tokens whose numeric part can't be parsed (e.g. "nl", "see")
    are skipped with a warning, or raise ValueError when strict: a
    correction's size is typed by hand and must parse whole.
    """
    if not raw:
        return SizeObject([])
    cleaned = raw.lower()
    for separator in ("x", "×", "/", "+"):
        cleaned = cleaned.replace(separator, " ")
    values = []
    for token in cleaned.split():
        arcsec = _size_token_to_arcsec(token)
        if arcsec is None and strict:
            raise ValueError(f"non-numeric size token {token!r} in {raw!r}")
        if arcsec is None:
            logging.warning("Non-numeric size token %r in %r", token, raw)
        else:
            values.append(arcsec)
    if not values:
        return SizeObject([])
    if len(values) == 2:
        values.sort(reverse=True)
    return SizeObject.from_arcsec(*values)


def safe_convert_to_float(x):
    """Convert to float, filtering out non-numeric values"""
    try:
        return float(x)
    except ValueError:
        return None


def add_space_after_prefix(s):
    """
    Convert a string like 'NGC1234' to 'NGC 1234'
    """
    # Use regex to match prefixes and numbers, and then join them with a space
    match = re.match(r"([a-zA-Z\-]+)(\d+)", s)
    if match:
        return " ".join(match.groups())
    return s


def trim_string(s):
    """Remove extra whitespace from string"""
    return " ".join(s.split())


# Designation prefixes that name a PiFinder catalog, keyed on the lowercase,
# whitespace-free prefix as source catalogs write it. A prefix must be listed
# here for an alias to link one object to another; every other designation is
# kept as a plain name. The same catalog is spelled several ways across
# sources, and SIMBAD writes Abell planetaries as "PN A66 nn".
#
# Deliberately absent:
# - A bare "h". Herschel 400 uses catalog code "H", but "H 1-1" and similar
#   names are Haro planetary nebulae, and a bare "H 12" can also be Hubble.
# - A bare "a" or "b". Double-star sources use them for the discoverers
#   Aitken and van den Bos ("A 58", "B 53"). A loader whose source means
#   Abell or Barnard passes them as extra_aliases to parse_designation.
# - "wds" and "pk". Their designations end in digits that are not a sequence
#   ("WDS 00001+7508", "PK 120+09.1").
CATALOG_CODE_ALIASES: Dict[str, str] = {
    "abell": "Abl",
    "abl": "Abl",
    "pna66": "Abl",
    "arp": "Arp",
    "barnard": "B",
    "c": "C",
    "caldwell": "C",
    "col": "Col",
    "collinder": "Col",
    "cr": "Col",
    "egc": "EGC",
    "har": "Har",
    "herschel": "H",
    "ic": "IC",
    "lyn": "Lyn",
    "m": "M",
    "messier": "M",
    "ngc": "NGC",
    "rds": "RDS",
    "saa": "SaA",
    "sam": "SaM",
    "sar": "SaR",
    "sh2": "Sh2",
    "sharpless": "Sh2",
    "str": "Str",
    "ta2": "Ta2",
    "tlk": "TLK",
}

# A designation reads "<prefix><sequence>": the sequence is the trailing run of
# digits, the prefix is everything before it.
_DESIGNATION_RE = re.compile(r"(.*?)\s*(\d+)")


def parse_designation(
    raw: str, extra_aliases: Optional[Dict[str, str]] = None
) -> Optional[Tuple[str, int]]:
    """Split a source designation into a PiFinder catalog code and sequence.

    "NGC 7008" -> ("NGC", 7008), "Sh 2-176" -> ("Sh2", 176),
    "PN A66 80" -> ("Abl", 80).

    Returns None when the designation names no PiFinder catalog. That covers
    the planetary-nebula families whose numeric part is compound: "M 1-92"
    (Minkowski), "H 3-29" (Haro), "K 2-1" (Kohoutek), "NGC 650-1" (the two
    halves of M76). Those leave a prefix of "m1", "h3", "k2" or "ngc650",
    none of which is a catalog, so they are rejected instead of being read as
    Messier 92, Herschel 29, "K 21" or NGC 6501.

    ``extra_aliases`` adds prefixes for one source, for example {"a": "Abl"}
    for a source that writes Abell planetaries as "A 50".
    """
    match = _DESIGNATION_RE.fullmatch(trim_string(raw).lower())
    if match is None:
        return None
    prefix, sequence = match.groups()
    key = prefix.rstrip("-.").replace(" ", "")
    catalog_code = CATALOG_CODE_ALIASES.get(key)
    if catalog_code is None and extra_aliases:
        catalog_code = extra_aliases.get(key)
    if catalog_code is None:
        return None
    return catalog_code, int(sequence)


def listing_named(name: str) -> Optional[Tuple[str, int]]:
    """The listing a name resolves to in the loaders' lookup, or None.

    parse_designation alone answers it, so its prefix allowlist governs every
    lookup: "B53" and "h99" name no listing, though Barnard 53 and Herschel
    400 #99 exist. ObjectFinder and the correction pass's checks
    (corrections.resolves_to) both ask this, so they cannot disagree.
    """
    return parse_designation(name)


def delete_catalog_from_database(catalog_code: str):
    """Delete a catalog and all its related records from the database"""
    if objects_db is None:
        raise RuntimeError("objects_db not initialized")
    conn, db_c = objects_db.get_conn_cursor()
    # 1. Delete related records from the `catalog_objects` table
    db_c.execute("DELETE FROM catalog_objects WHERE catalog_code = ?", (catalog_code,))
    # 2. Delete the catalog record from the `catalogs` table
    db_c.execute("DELETE FROM catalogs WHERE catalog_code = ?", (catalog_code,))
    conn.commit()


def insert_catalog(catalog_name, description_path):
    """Insert a catalog description into the database"""
    with open(description_path, "r") as desc:
        description = "".join(desc.readlines())
    objects_db.insert_catalog(catalog_name, -1, description)


def insert_catalog_max_sequence(catalog_name):
    """Update the max_sequence for a catalog based on actual data"""
    conn, db_c = objects_db.get_conn_cursor()
    query = f"""
            SELECT MAX(sequence) FROM catalog_objects
            where catalog_code = '{catalog_name}' GROUP BY catalog_code
        """
    db_c.execute(query)
    result = db_c.fetchone()
    if result:
        query = f"""
            update catalogs set max_sequence = {
            dict(result)['MAX(sequence)']} where catalog_code = '{catalog_name}'
            """
        db_c.execute(query)
        conn.commit()


def count_rows_per_distinct_column(conn, db_c, table, column):
    """Count rows per distinct value in a column"""
    db_c.execute(f"SELECT {column}, COUNT(*) FROM {table} GROUP BY {column}")
    result = db_c.fetchall()
    for row in result:
        logging.info(f"{row[0]}: {row[1]} entries")


def get_catalog_counts():
    """Get count of objects per catalog"""
    _conn, db_c = objects_db.get_conn_cursor()
    db_c.execute(
        "SELECT catalog_code, count(*) from catalog_objects group by catalog_code"
    )
    result = list(db_c.fetchall())
    for row in result:
        logging.info(f"{row[0]}: {row[1]} entries")
    return result


def count_empty_entries(conn, db_c, table, columns):
    """Count empty entries in specified columns"""
    db_c = conn.cursor()
    for column in columns:
        db_c.execute(
            f"""
                SELECT COUNT(*) FROM {table}
                WHERE {column} IS NULL OR {column} = ''
            """
        )
        result = db_c.fetchone()
        logging.info(f"{column}: {result[0]} empty entries")


def count_common_names_per_catalog():
    """Count common names per catalog"""
    conn, db_c = objects_db.get_conn_cursor()
    count_rows_per_distinct_column(conn, db_c, "names", "origin")


def count_empty_entries_in_tables():
    """Count empty entries across important tables"""
    conn, db_c = objects_db.get_conn_cursor()
    count_empty_entries(conn, db_c, "names", ["object_id", "common_name", "origin"])
    count_empty_entries(
        conn,
        db_c,
        "objects",
        [
            "obj_type",
            "ra",
            "dec",
            "const",
            "size",
            "mag",
        ],
    )


def count_nonempty_sizes_per_catalog():
    """Report per-catalog coverage of non-empty size extents.

    A valid-but-empty size payload ({"e": []}) still counts as "has a size"
    when you only check for a JSON payload, so a size-parsing regression can
    silently wipe a catalog's extents without tripping a presence check. This
    counts payloads that actually carry extents, joining catalog_objects to
    objects since size lives on the object (shared across catalogs).
    """
    _, db_c = objects_db.get_conn_cursor()
    rows = db_c.execute(
        """
        SELECT co.catalog_code AS catalog_code,
               COUNT(*) AS total,
               SUM(
                   CASE WHEN o.size IS NOT NULL
                             AND o.size != ''
                             AND o.size NOT LIKE '%"e": []%'
                        THEN 1 ELSE 0 END
               ) AS with_size
        FROM catalog_objects co
        JOIN objects o ON o.id = co.object_id
        GROUP BY co.catalog_code
        ORDER BY co.catalog_code
        """
    ).fetchall()
    logging.info("Size extent coverage per catalog (objects with non-empty extents):")
    for row in rows:
        total = row["total"]
        with_size = row["with_size"] or 0
        pct = (with_size / total * 100) if total else 0.0
        logging.info(
            "  %-8s %6d/%-6d (%3.0f%%)",
            row["catalog_code"],
            with_size,
            total,
            pct,
        )


def print_database():
    """Print database statistics"""
    logging.info(">-------------------------------------------------------")
    count_common_names_per_catalog()
    count_empty_entries_in_tables()
    count_nonempty_sizes_per_catalog()
    logging.info("<-------------------------------------------------------")


def resolve_object_images():
    """Resolve object images based on catalog priority - Optimized version"""
    conn, db_c = objects_db.get_conn_cursor()

    # Get catalog priority order
    resolution_priority = db_c.execute(
        """
            SELECT catalog_code
            FROM catalogs
            ORDER BY rowid
        """
    ).fetchall()

    # Build priority order list for easier processing
    catalog_priority = [entry["catalog_code"] for entry in resolution_priority]

    # Use a single complex query to get all catalog mappings at once
    # This creates a priority-ordered result set
    priority_cases = []
    for i, catalog_code in enumerate(catalog_priority):
        priority_cases.append(f"WHEN catalog_code = '{catalog_code}' THEN {i}")

    priority_case_sql = "CASE " + " ".join(priority_cases) + " ELSE 999 END"

    # Single query to get the highest priority catalog entry for each object
    query = f"""
        WITH ranked_catalogs AS (
            SELECT 
                co.object_id,
                co.catalog_code,
                co.sequence,
                ROW_NUMBER() OVER (
                    PARTITION BY co.object_id 
                    ORDER BY {priority_case_sql}
                ) as priority_rank
            FROM catalog_objects co
            WHERE co.catalog_code IN ({','.join(['?'] * len(catalog_priority))})
        )
        SELECT 
            o.id as object_id,
            rc.catalog_code,
            rc.sequence
        FROM objects o
        LEFT JOIN ranked_catalogs rc ON o.id = rc.object_id AND rc.priority_rank = 1
        ORDER BY o.id
    """

    # Execute with catalog codes as parameters
    results = db_c.execute(query, catalog_priority).fetchall()

    # Prepare bulk insert data
    image_objects_to_insert = []
    unresolved_objects = []

    for row in tqdm(results, desc="Resolving object images"):
        object_id = row["object_id"]
        catalog_code = row["catalog_code"]
        sequence = row["sequence"]

        if catalog_code and sequence is not None:
            resolved_name = f"{catalog_code}{sequence}"
            image_objects_to_insert.append((object_id, resolved_name))
        else:
            unresolved_objects.append(object_id)

    # Bulk insert image objects
    if image_objects_to_insert:
        # Use executemany for bulk insert into the correct table
        db_c.executemany(
            "INSERT INTO object_images (object_id, image_name) VALUES (?, ?)",
            image_objects_to_insert,
        )
        conn.commit()
        logging.info(f"Resolved {len(image_objects_to_insert)} object images")

    # Log unresolved objects
    if unresolved_objects:
        logging.warning(
            f"No catalog entries for {len(unresolved_objects)} objects: {unresolved_objects[:10]}{'...' if len(unresolved_objects) > 10 else ''}"
        )


def dedup_names():
    """
    Goes through the names table and makes sure there is only one
    of each name

    CURRENTLY only prints duplicates for inspection
    """

    _conn, db_c = ObjectsDatabase().get_conn_cursor()
    # get all names
    names = db_c.execute("select object_id, common_name from names").fetchall()

    name_dict = {}
    for name_rec in names:
        if name_rec["common_name"] not in name_dict.keys():
            name_dict[name_rec["common_name"]] = name_rec["object_id"]
        else:
            if name_rec["object_id"] != name_dict[name_rec["common_name"]]:
                print("FAIL")
                print(name_rec["common_name"], name_rec["object_id"])


def init_databases():
    """Initialize global database objects"""
    global objects_db, observations_db
    objects_db = ObjectsDatabase()
    observations_db = ObservationsDatabase()

    # Also initialize the module-level globals in all loader modules
    import PiFinder.catalog_imports.steinicke_loader as steinicke_mod
    import PiFinder.catalog_imports.caldwell_loader as caldwell_mod
    import PiFinder.catalog_imports.post_processing as postproc_mod
    import PiFinder.catalog_imports.specialized_loaders as specialized_mod
    import PiFinder.catalog_imports.bright_stars_loader as bright_stars_mod
    import PiFinder.catalog_imports.herschel_loader as herschel_mod
    import PiFinder.catalog_imports.sac_loaders as sac_mod

    steinicke_mod.objects_db = objects_db
    caldwell_mod.objects_db = objects_db
    postproc_mod.objects_db = objects_db
    specialized_mod.objects_db = objects_db
    bright_stars_mod.objects_db = objects_db
    herschel_mod.objects_db = objects_db
    sac_mod.objects_db = objects_db

    return objects_db, observations_db
