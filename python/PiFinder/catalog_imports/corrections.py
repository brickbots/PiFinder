"""
Corrections: cited, checked values that replace what a source gives.

A correction fixes a value that a published source has wrong for one sky
object, where no loader fix or supplementary source can produce the right
one (ADR 0046, docs/ax/catalog.md section 9.5). Corrections live in
astro_data/corrections/<source>.toml, one table per designator; the format
is documented in that directory's README.md.

load_corrections() reads and validates the files. apply_corrections() is the
import's final pass: it runs after every other stage, so a correction always
has the last word, and it fails the import on any correction that is stale,
redundant, unresolvable or in conflict with another. The one correction it
does not apply is `hip`, which feeds the star cross-match instead: that stage
reads hip_identifications() before it matches.
"""

import logging
import math
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, cast

from skyfield.api import load_constellation_names

import PiFinder.utils as utils
from PiFinder import calc_utils
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.obj_types import OBJ_TYPES
from .catalog_import_utils import parse_arcmin_size

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CORRECTIONS_DIR = Path(utils.astro_data_dir) / "corrections"

# Fields a correction can set, named like the database columns. A
# description belongs to one catalog listing; the rest to the sky object.
SKY_OBJECT_FIELDS = ("obj_type", "ra", "dec", "const", "size", "mag")
LISTING_FIELDS = ("description",)
FIELDS = SKY_OBJECT_FIELDS + LISTING_FIELDS

# How close a field must be to count as holding a value, for the `was`
# (stale) and redundancy checks.
MAG_TOLERANCE = 0.05
POSITION_TOLERANCE_DEG = 1 / 3600  # 1 arcsecond, on RA and Dec separately
SIZE_TOLERANCE_ARCSEC = 1.0
_FLOAT_SLACK = 1e-9

_KEYS = {"why", "sources", "was", "names", "same_as", "own_object", "hip", *FIELDS}
_NAME_KEYS = {"add", "remove", "preferred"}

# A catalog code, one space, and a number without leading zeros: "NGC 604",
# "Sh2 155". The code must match catalog_objects.catalog_code exactly.
_DESIGNATOR = re.compile(r"([A-Za-z][A-Za-z0-9]*) ([1-9][0-9]*)")

_CONSTELLATIONS = {abbreviation for abbreviation, _name in load_constellation_names()}


class CorrectionError(Exception):
    """One or more corrections are invalid, so the import must not finish."""

    def __init__(self, problems: List[str]):
        self.problems = problems
        lines = "\n".join(f"  {problem}" for problem in problems)
        super().__init__(f"{len(problems)} correction problem(s):\n{lines}")


@dataclass
class Correction:
    """One designator's table from a corrections file, parsed and validated.

    Field values are held in comparable form: RA and Dec in degrees, a size
    as its extents in arcseconds, a magnitude as its list of mags.
    """

    source_file: str
    designator: str
    listing: Tuple[str, int]
    why: str
    sources: List[str]
    fields: Dict[str, Any] = field(default_factory=dict)
    was: Dict[str, Any] = field(default_factory=dict)
    names_add: List[str] = field(default_factory=list)
    names_remove: List[str] = field(default_factory=list)
    names_preferred: Optional[str] = None
    same_as: Optional[Tuple[str, int]] = None
    own_object: bool = False
    hip: Optional[int] = None

    @property
    def label(self) -> str:
        return f"{self.source_file} [{self.designator}]"

    def names_touched(self) -> List[str]:
        preferred = [self.names_preferred] if self.names_preferred else []
        return self.names_add + self.names_remove + preferred


# ---- parsing values ----


def parse_designator(text: Any) -> Tuple[str, int]:
    """'NGC 604' -> ('NGC', 604)."""
    match = _DESIGNATOR.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        raise ValueError(
            f"{text!r} is not a designator: write a catalog code, one space and"
            ' a number, such as "NGC 604"'
        )
    return match.group(1), int(match.group(2))


_SEXAGESIMAL_SEPARATORS = re.compile(r"[\s:hmsd°'′\"″]+")
_UNSIGNED_NUMBER = re.compile(r"[0-9]+(\.[0-9]+)?")


def _sexagesimal(text: Any, what: str, example: str) -> Tuple[str, float]:
    """Split '-05 23 28' into ('-', 5.391...); 2 or 3 parts, last may be decimal."""
    if not isinstance(text, str):
        raise ValueError(f"{what} must be a sexagesimal string, such as {example}")
    text = text.strip()
    sign = text[0] if text and text[0] in "+-" else ""
    parts = [part for part in _SEXAGESIMAL_SEPARATORS.split(text[len(sign) :]) if part]
    if not 2 <= len(parts) <= 3 or not all(
        _UNSIGNED_NUMBER.fullmatch(part) for part in parts
    ):
        raise ValueError(f"{what} {text!r} is not sexagesimal, such as {example}")
    if any("." in part for part in parts[:-1]):
        raise ValueError(f"{what} {text!r}: only its last part may have decimals")
    numbers = [float(part) for part in parts]
    if any(number >= 60 for number in numbers[1:]):
        raise ValueError(f"{what} {text!r}: minutes and seconds must be under 60")
    value = sum(number / 60**i for i, number in enumerate(numbers))
    return sign, value


def parse_ra(text: Any) -> float:
    """Sexagesimal hours ('05 35 17.3', '05:35:17.3', '5h35m17.3s') to degrees."""
    sign, hours = _sexagesimal(text, "ra", '"05 35 17.3"')
    if sign or hours >= 24:
        raise ValueError(f"ra {text!r} must be unsigned hours under 24")
    return hours * 15


def parse_dec(text: Any) -> float:
    """Sexagesimal degrees ('-05 23 28', '+41°16′09″') to degrees."""
    sign, degrees = _sexagesimal(text, "dec", '"-05 23 28"')
    if degrees > 90:
        raise ValueError(f"dec {text!r} is beyond the pole")
    return -degrees if sign == "-" else degrees


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _parse_obj_type(value: Any) -> str:
    if value not in OBJ_TYPES:
        raise ValueError(
            f"obj_type {value!r} is not a type code; use one of " + ", ".join(OBJ_TYPES)
        )
    return value


def _parse_const(value: Any) -> str:
    if value not in _CONSTELLATIONS:
        raise ValueError(f"const {value!r} is not an IAU constellation abbreviation")
    return value


def _parse_size(value: Any) -> List[float]:
    if not isinstance(value, str):
        raise ValueError(f'size must be a string, such as "2.5\'", not {value!r}')
    extents = cast(List[float], parse_arcmin_size(value, strict=True).extents)
    if not extents:
        raise ValueError(f"size {value!r} holds no size")
    return extents


def _parse_mag(value: Any) -> List[float]:
    values = value if isinstance(value, list) else [value]
    if not values or not all(_is_number(mag) for mag in values):
        raise ValueError(
            f"mag must be a number, or a list of numbers for a variable's range,"
            f" not {value!r}"
        )
    return [float(mag) for mag in values]


def _parse_description(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("description must be a non-empty string")
    return value.strip()


_FIELD_PARSERS: Dict[str, Callable[[Any], Any]] = {
    "obj_type": _parse_obj_type,
    "ra": parse_ra,
    "dec": parse_dec,
    "const": _parse_const,
    "size": _parse_size,
    "mag": _parse_mag,
    "description": _parse_description,
}

# Fields that can be empty in the database, and so can be `was = ""`.
_EMPTY: Dict[str, Callable[[], Any]] = {
    "size": list,
    "mag": list,
    "description": str,
}


def _parse_was(field_name: str, value: Any) -> Any:
    if value == "" and field_name in _EMPTY:
        return _EMPTY[field_name]()
    return _FIELD_PARSERS[field_name](value)


# ---- comparing and showing values ----


def _same_number(a: Any, b: Any, tolerance: float) -> bool:
    if _is_number(a) and _is_number(b):
        return abs(a - b) <= tolerance + _FLOAT_SLACK
    return a == b


def _same_list(a: List[Any], b: List[Any], tolerance: float) -> bool:
    return len(a) == len(b) and all(_same_number(x, y, tolerance) for x, y in zip(a, b))


def same_value(field_name: str, a: Any, b: Any) -> bool:
    """Whether two values of a field agree, within that field's tolerance."""
    if field_name in ("ra", "dec"):
        if not (_is_number(a) and _is_number(b)):
            return a == b
        difference = abs(a - b)
        if field_name == "ra":
            difference = min(difference, 360 - difference)
        return difference <= POSITION_TOLERANCE_DEG + _FLOAT_SLACK
    if field_name == "size":
        return _same_list(a, b, SIZE_TOLERANCE_ARCSEC)
    if field_name == "mag":
        return _same_list(a, b, MAG_TOLERANCE)
    return a == b


def _format_ra(degrees: float) -> str:
    hundredths = round(degrees / 15 * 360000)
    hours, rest = divmod(hundredths, 360000)
    minutes, rest = divmod(rest, 6000)
    return f"{hours:02d} {minutes:02d} {rest / 100:05.2f}"


def _format_dec(degrees: float) -> str:
    sign = "-" if degrees < 0 else "+"
    tenths = round(abs(degrees) * 36000)
    whole, rest = divmod(tenths, 36000)
    minutes, rest = divmod(rest, 600)
    return f"{sign}{whole:02d} {minutes:02d} {rest / 10:04.1f}"


def format_value(field_name: str, value: Any) -> str:
    """A value as it would be written in a corrections file."""
    if value in ("", []):
        return '""'
    if field_name == "ra" and _is_number(value):
        return f'"{_format_ra(value)}"'
    if field_name == "dec" and _is_number(value):
        return f'"{_format_dec(value)}"'
    if field_name == "size":
        return repr(SizeObject(value).to_display_string())
    if field_name == "mag":
        return str(value[0]) if len(value) == 1 else str(value)
    return repr(value)


# ---- loading ----


def load_corrections(directory: Path = CORRECTIONS_DIR) -> List[Correction]:
    """Read and validate every corrections file, in file-name order.

    Raises CorrectionError listing every problem found in any file.
    """
    corrections: List[Correction] = []
    problems: List[str] = []
    for path in sorted(Path(directory).glob("*.toml")):
        try:
            with open(path, "rb") as file:
                document = tomllib.load(file)
        except tomllib.TOMLDecodeError as error:
            problems.append(f"{path.name}: not valid TOML: {error}")
            continue
        for designator, table in document.items():
            try:
                corrections.append(_parse_correction(path.name, designator, table))
            except CorrectionError as error:
                problems.extend(error.problems)
    if problems:
        raise CorrectionError(problems)
    logging.info("Loaded %d corrections from %s", len(corrections), directory)
    return corrections


def _string_list(value: Any) -> Optional[List[str]]:
    """The stripped strings of a non-empty list of non-empty strings, or None."""
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(item, str) and item.strip() for item in value):
        return None
    return [item.strip() for item in value]


def _parse_correction(source_file: str, designator: str, table: Any) -> Correction:
    label = f"{source_file} [{designator}]"
    problems: List[str] = []

    def problem(message: str) -> None:
        problems.append(f"{label}: {message}")

    if not isinstance(table, dict):
        raise CorrectionError(
            [f"{label}: must be a table, with the designator quoted in its header"]
        )
    try:
        listing = parse_designator(designator)
    except ValueError as error:
        problem(str(error))
        listing = ("", 0)

    for key in sorted(set(table) - _KEYS):
        problem(f"unknown key {key!r}")

    why = table.get("why")
    if not isinstance(why, str) or not why.strip():
        problem("needs `why`: what is wrong, and what the sources say")
        why = ""
    sources = _string_list(table.get("sources"))
    if sources is None:
        problem("needs `sources`: a list of citations (URLs where they exist)")
        sources = []

    correction = Correction(source_file, designator, listing, why.strip(), sources)

    for field_name in FIELDS:
        if field_name in table:
            try:
                correction.fields[field_name] = _FIELD_PARSERS[field_name](
                    table[field_name]
                )
            except ValueError as error:
                problem(str(error))

    was = table.get("was", {})
    if not isinstance(was, dict):
        problem('`was` must be a table of fields, such as was.size = "120\'"')
        was = {}
    for field_name in was:
        if field_name not in FIELDS:
            problem(f"was.{field_name} is not a field")
        elif field_name not in table:
            problem(f"was.{field_name} without a {field_name} to correct")
        else:
            try:
                correction.was[field_name] = _parse_was(field_name, was[field_name])
            except ValueError as error:
                problem(f"was.{field_name}: {error}")
    for field_name, value in correction.fields.items():
        if field_name not in was:
            problem(
                f"{field_name} needs was.{field_name}, the value it replaces"
                ' ("" if the field is empty)'
            )
        elif field_name in correction.was and same_value(
            field_name, value, correction.was[field_name]
        ):
            problem(f"{field_name} equals was.{field_name}, so it corrects nothing")

    _parse_names(table.get("names"), correction, problem)
    _parse_identification(table, correction, problem)

    if not (
        correction.fields
        or correction.names_touched()
        or correction.same_as
        or correction.own_object
        or correction.hip is not None
        or problems
    ):
        problem("corrects nothing")
    if problems:
        raise CorrectionError(problems)
    return correction


def _parse_names(
    names: Any, correction: Correction, problem: Callable[[str], None]
) -> None:
    if names is None:
        return
    if not isinstance(names, dict):
        problem("`names` must be a table: names.add, names.remove, names.preferred")
        return
    for key in sorted(set(names) - _NAME_KEYS):
        problem(f"unknown key names.{key}")
    for key in ("add", "remove"):
        if key in names:
            values = _string_list(names[key])
            if values is None:
                problem(f"names.{key} must be a non-empty list of names")
            elif len(set(values)) != len(values):
                problem(f"names.{key} lists a name twice")
            else:
                setattr(correction, f"names_{key}", values)
    if "preferred" in names:
        preferred = names["preferred"]
        if not isinstance(preferred, str) or not preferred.strip():
            problem("names.preferred must be a name")
        else:
            correction.names_preferred = preferred.strip()
    overlap = set(correction.names_add) & set(correction.names_remove)
    if overlap:
        problem(f"names.add and names.remove both list {sorted(overlap)}")
    preferred = correction.names_preferred
    if preferred in correction.names_add:
        problem(f"names.preferred adds {preferred!r} already; drop it from names.add")
    if preferred in correction.names_remove:
        problem(f"names.preferred {preferred!r} is also in names.remove")


def _parse_identification(
    table: Dict[str, Any], correction: Correction, problem: Callable[[str], None]
) -> None:
    if "same_as" in table:
        try:
            correction.same_as = parse_designator(table["same_as"])
        except ValueError as error:
            problem(f"same_as: {error}")
        else:
            if correction.same_as == correction.listing:
                problem("same_as names the designator itself")
    if "own_object" in table:
        if table["own_object"] is not True:
            problem("own_object can only be true")
        else:
            correction.own_object = True
    if correction.same_as and correction.own_object:
        problem("same_as and own_object contradict each other")
    if "hip" in table:
        hip = table["hip"]
        if isinstance(hip, bool) or not isinstance(hip, int) or hip <= 0:
            problem(f"hip must be a Hipparcos number, not {hip!r}")
        else:
            correction.hip = hip


def hip_identifications(corrections: Iterable[Correction]) -> Dict[str, int]:
    """Map each designator with a `hip` correction to its Hipparcos number.

    For the star-identity stage, which uses these in place of position when it
    cross-matches star listings to Hipparcos. The final pass leaves `hip`
    alone, since by then the cross-match has already run.
    """
    identifications: Dict[str, int] = {}
    labels: Dict[str, str] = {}
    problems = []
    for correction in corrections:
        if correction.hip is None:
            continue
        if correction.designator in identifications:
            problems.append(
                f"{correction.label}: conflicts with {labels[correction.designator]}:"
                " both set hip"
            )
            continue
        identifications[correction.designator] = correction.hip
        labels[correction.designator] = correction.label
    if problems:
        raise CorrectionError(problems)
    return identifications


# ---- the final pass ----


def apply_corrections(db: ObjectsDatabase, corrections: List[Correction]) -> None:
    """The import's final pass: apply every correction, or none.

    Identifications go first, splits (own_object) before joins (same_as),
    since they change what designators resolve to. Then every field and name
    correction is checked against the database before any is written. Any
    problem rolls the pass back and raises CorrectionError.
    """
    conn = db.conn
    try:
        _apply(conn.cursor(), corrections)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def _apply(cursor: sqlite3.Cursor, corrections: List[Correction]) -> None:
    moved = _apply_identifications(cursor, corrections)
    planned = _plan(cursor, corrections)
    for correction, listing_id, object_id in planned:
        _write(cursor, correction, listing_id, object_id)
    _recompute_constellations(cursor, planned)
    _check_nothing_left_behind(cursor, moved)
    logging.info(
        "Applied %d corrections (hip identifications are left to the star"
        " cross-match: %d)",
        len(corrections),
        sum(correction.hip is not None for correction in corrections),
    )


def _designator(listing: Tuple[str, int]) -> str:
    return f"{listing[0]} {listing[1]}"


def _name_key(name: str) -> str:
    """How a loader's lookup compares designations: case and spaces ignored."""
    return "".join(name.split()).lower()


def _resolve(
    cursor: sqlite3.Cursor, listing: Tuple[str, int]
) -> Tuple[Optional[sqlite3.Row], str]:
    """The catalog_objects row a designator names, or None and why not."""
    rows = cursor.execute(
        "SELECT id, object_id FROM catalog_objects"
        " WHERE catalog_code = ? AND sequence = ?",
        listing,
    ).fetchall()
    if len(rows) == 1:
        return rows[0], ""
    if rows:
        return None, f"{_designator(listing)} is listed {len(rows)} times"
    known = cursor.execute(
        "SELECT 1 FROM catalogs WHERE catalog_code = ?", (listing[0],)
    ).fetchone()
    if known is None:
        return None, f"no catalog has the code {listing[0]!r}"
    return None, f"{_designator(listing)} resolves to nothing"


def _names(cursor: sqlite3.Cursor, object_id: int) -> List[sqlite3.Row]:
    return cursor.execute(
        "SELECT id, common_name, origin FROM names WHERE object_id = ? ORDER BY id",
        (object_id,),
    ).fetchall()


def _listings(cursor: sqlite3.Cursor, object_id: int) -> List[sqlite3.Row]:
    return cursor.execute(
        "SELECT id, catalog_code, sequence FROM catalog_objects"
        " WHERE object_id = ? ORDER BY id",
        (object_id,),
    ).fetchall()


def _move_names(
    cursor: sqlite3.Cursor, rows: Iterable[sqlite3.Row], object_id: int
) -> None:
    """Move name rows to the end of another sky object's names.

    Re-inserted rather than re-pointed, so a moved name can't land ahead of
    the names already there; a name the sky object already has is dropped.
    """
    present = {row["common_name"] for row in _names(cursor, object_id)}
    for row in rows:
        cursor.execute("DELETE FROM names WHERE id = ?", (row["id"],))
        if row["common_name"] not in present:
            cursor.execute(
                "INSERT INTO names (object_id, common_name, origin) VALUES (?, ?, ?)",
                (object_id, row["common_name"], row["origin"]),
            )
            present.add(row["common_name"])


def _move_listing(
    cursor: sqlite3.Cursor,
    correction: Correction,
    listing_id: int,
    from_object: int,
    to_object: int,
) -> None:
    """Move one catalog listing, and the names that are its designator."""
    cursor.execute(
        "UPDATE catalog_objects SET object_id = ? WHERE id = ?", (to_object, listing_id)
    )
    key = _name_key(correction.designator)
    own_names = [
        row
        for row in _names(cursor, from_object)
        if row["origin"] == correction.listing[0]
        and _name_key(row["common_name"]) == key
    ]
    _move_names(cursor, own_names, to_object)
    if not any(
        _name_key(row["common_name"]) == key for row in _names(cursor, to_object)
    ):
        cursor.execute(
            "INSERT INTO names (object_id, common_name, origin) VALUES (?, ?, ?)",
            (to_object, correction.designator, correction.listing[0]),
        )


def _apply_identifications(
    cursor: sqlite3.Cursor, corrections: List[Correction]
) -> List[Tuple[Correction, int]]:
    """Apply own_object and same_as; return each with the sky object it left."""
    identifications = [c for c in corrections if c.own_object or c.same_as]
    problems: List[str] = []
    claimed: Dict[Tuple[str, int], Correction] = {}
    for correction in identifications:
        other = claimed.setdefault(correction.listing, correction)
        if other is not correction:
            problems.append(
                f"{correction.label}: conflicts with {other.label}: both correct"
                f" the identification of {correction.designator}"
            )
    joining = {c.listing for c in identifications if c.same_as}
    for correction in identifications:
        if correction.same_as in joining:
            problems.append(
                f"{correction.label}: same_as {_designator(correction.same_as)},"
                " which is itself corrected by a same_as; point"
                f" {correction.designator} at the sky object it ends up on"
            )
    if problems:
        raise CorrectionError(problems)

    moved: List[Tuple[Correction, int]] = []
    splits_first = sorted(identifications, key=lambda c: not c.own_object)
    for correction in splits_first:
        listing, why_not = _resolve(cursor, correction.listing)
        if listing is None:
            problems.append(f"{correction.label}: {why_not}")
            continue
        source = listing["object_id"]
        siblings = len(_listings(cursor, source)) - 1
        if correction.own_object:
            if not siblings:
                problems.append(
                    f"{correction.label}: own_object, but {correction.designator}"
                    " is already a sky object of its own"
                )
                continue
            cursor.execute(
                "INSERT INTO objects"
                " (obj_type, ra, dec, const, size, mag, surface_brightness)"
                " SELECT obj_type, ra, dec, const, size, mag, surface_brightness"
                " FROM objects WHERE id = ?",
                (source,),
            )
            new_object = cursor.lastrowid
            assert new_object is not None
            _move_listing(cursor, correction, listing["id"], source, new_object)
        else:
            assert correction.same_as is not None
            target_designator = _designator(correction.same_as)
            target, why_not = _resolve(cursor, correction.same_as)
            if target is None:
                problems.append(f"{correction.label}: same_as: {why_not}")
                continue
            if target["object_id"] == source:
                problems.append(
                    f"{correction.label}: same_as {target_designator}, but it is"
                    " already the same sky object"
                )
                continue
            if siblings:
                _move_listing(
                    cursor, correction, listing["id"], source, target["object_id"]
                )
            else:
                # The whole sky object is this listing: merge it in.
                cursor.execute(
                    "UPDATE catalog_objects SET object_id = ? WHERE id = ?",
                    (target["object_id"], listing["id"]),
                )
                _move_names(cursor, _names(cursor, source), target["object_id"])
                cursor.execute(
                    "DELETE FROM object_images WHERE object_id = ?", (source,)
                )
                cursor.execute("DELETE FROM objects WHERE id = ?", (source,))
        moved.append((correction, source))
    if problems:
        raise CorrectionError(problems)
    return moved


def _plan(
    cursor: sqlite3.Cursor, corrections: List[Correction]
) -> List[Tuple[Correction, int, int]]:
    """Resolve every correction and check it, before anything is written.

    Returns (correction, listing id, sky object id) for each.
    """
    problems: List[str] = []
    planned: List[Tuple[Correction, int, int]] = []
    claims: Dict[Tuple[Any, ...], Correction] = {}
    conflicts: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for correction in corrections:
        listing, why_not = _resolve(cursor, correction.listing)
        if listing is None:
            problems.append(f"{correction.label}: {why_not}")
            continue
        listing_id, object_id = listing["id"], listing["object_id"]
        planned.append((correction, listing_id, object_id))

        claimed: List[Tuple[Tuple[Any, ...], str]] = []
        for field_name in correction.fields:
            if field_name in SKY_OBJECT_FIELDS:
                claimed.append(((object_id, field_name), field_name))
            else:
                claimed.append((("listing", listing_id, field_name), field_name))
        if correction.names_preferred:
            claimed.append(((object_id, "names.preferred"), "names.preferred"))
        for name in correction.names_touched():
            claimed.append(((object_id, "name", name), f"the name {name!r}"))
        if correction.hip is not None:
            claimed.append((("listing", listing_id, "hip"), "hip"))
        for key, what in claimed:
            other = claims.setdefault(key, correction)
            if other is not correction:
                conflicts[(correction.label, other.label)].append(what)
    for (label, other_label), whats in conflicts.items():
        problems.append(
            f"{label}: conflicts with {other_label}: both correct "
            + ", ".join(dict.fromkeys(whats))
            + " of the same sky object"
        )
    for correction, listing_id, object_id in planned:
        problems.extend(_check(cursor, correction, listing_id, object_id))
    if problems:
        raise CorrectionError(problems)
    return planned


def _current_values(
    cursor: sqlite3.Cursor, listing_id: int, object_id: int
) -> Dict[str, Any]:
    sky_object = cursor.execute(
        "SELECT * FROM objects WHERE id = ?", (object_id,)
    ).fetchone()
    listing = cursor.execute(
        "SELECT description FROM catalog_objects WHERE id = ?", (listing_id,)
    ).fetchone()
    return {
        "obj_type": sky_object["obj_type"] or "",
        "ra": sky_object["ra"],
        "dec": sky_object["dec"],
        "const": sky_object["const"] or "",
        "size": SizeObject.from_json(sky_object["size"]).extents,
        "mag": MagnitudeObject.from_json(sky_object["mag"]).mags,
        "description": (listing["description"] or "").strip(),
    }


def _check(
    cursor: sqlite3.Cursor, correction: Correction, listing_id: int, object_id: int
) -> List[str]:
    """The stale and redundant checks, for fields and names alike."""
    problems = []
    label = correction.label
    current = _current_values(cursor, listing_id, object_id)
    for field_name, value in correction.fields.items():
        holds = current[field_name]
        if same_value(field_name, holds, value):
            problems.append(
                f"{label}: {field_name} is already {format_value(field_name, value)};"
                " the correction is redundant, so delete it"
            )
        elif not same_value(field_name, holds, correction.was[field_name]):
            problems.append(
                f"{label}: {field_name} is stale: was.{field_name} says"
                f" {format_value(field_name, correction.was[field_name])}, but the"
                f" database holds {format_value(field_name, holds)}; check the"
                " correction against the source"
            )
    names = [row["common_name"] for row in _names(cursor, object_id)]
    for name in correction.names_remove:
        if name not in names:
            problems.append(
                f"{label}: names.remove {name!r}, which the sky object doesn't have"
            )
    for name in correction.names_add:
        if name in names:
            problems.append(f"{label}: names.add {name!r}, which it already has")
    if names and correction.names_preferred == names[0]:
        problems.append(
            f"{label}: names.preferred {names[0]!r} is already the first name"
        )
    return problems


def _write(
    cursor: sqlite3.Cursor, correction: Correction, listing_id: int, object_id: int
) -> None:
    for field_name, value in correction.fields.items():
        if field_name == "description":
            cursor.execute(
                "UPDATE catalog_objects SET description = ? WHERE id = ?",
                (value, listing_id),
            )
            continue
        if field_name == "size":
            # The extents are corrected; the position angle stays as it was.
            stored = cursor.execute(
                "SELECT size FROM objects WHERE id = ?", (object_id,)
            ).fetchone()["size"]
            position_angle = SizeObject.from_json(stored).position_angle
            value = SizeObject(value, position_angle=position_angle).to_json()
        elif field_name == "mag":
            value = MagnitudeObject(list(value)).to_json()
        cursor.execute(
            f"UPDATE objects SET {field_name} = ? WHERE id = ?", (value, object_id)
        )

    code = correction.listing[0]
    for name in correction.names_remove:
        cursor.execute(
            "DELETE FROM names WHERE object_id = ? AND common_name = ?",
            (object_id, name),
        )
    for name in correction.names_add:
        cursor.execute(
            "INSERT INTO names (object_id, common_name, origin) VALUES (?, ?, ?)",
            (object_id, name, code),
        )
    preferred = correction.names_preferred
    if preferred:
        # Names are ordered by row id, so putting one first means re-inserting
        # them all, the preferred name's rows ahead of the rest.
        rows = [
            (row["common_name"], row["origin"]) for row in _names(cursor, object_id)
        ]
        first = [row for row in rows if row[0] == preferred] or [(preferred, code)]
        rest = [row for row in rows if row[0] != preferred]
        cursor.execute("DELETE FROM names WHERE object_id = ?", (object_id,))
        cursor.executemany(
            "INSERT INTO names (object_id, common_name, origin) VALUES (?, ?, ?)",
            [(object_id, name, origin) for name, origin in first + rest],
        )


def _recompute_constellations(
    cursor: sqlite3.Cursor, planned: List[Tuple[Correction, int, int]]
) -> None:
    """A moved sky object's constellation follows its position, as at insert,
    unless a correction sets const itself (a boundary case like NGC 1404)."""
    moved: Dict[int, str] = {}
    const_set: Set[int] = set()
    for correction, _listing_id, object_id in planned:
        if "ra" in correction.fields or "dec" in correction.fields:
            moved.setdefault(object_id, correction.designator)
        if "const" in correction.fields:
            const_set.add(object_id)
    for object_id, designator in moved.items():
        if object_id in const_set:
            continue
        row = cursor.execute(
            "SELECT ra, dec, const FROM objects WHERE id = ?", (object_id,)
        ).fetchone()
        const = calc_utils.sf_utils.radec_to_constellation(row["ra"], row["dec"])
        logging.info(
            "Constellation of %s follows its corrected position: %s -> %s",
            designator,
            row["const"],
            const,
        )
        cursor.execute("UPDATE objects SET const = ? WHERE id = ?", (const, object_id))


def _check_nothing_left_behind(
    cursor: sqlite3.Cursor, moved: List[Tuple[Correction, int]]
) -> None:
    """Fail a split or join whose old sky object still answers to its designator.

    Another catalog's name equal to the moved designator means that catalog's
    listing was matched through the wrong identification, and it stays behind
    on the old sky object, or that its record asserts the cross-identification
    the correction denies (Steinicke's NGC records carry the "M nn" names).
    Runs after names corrections, so a stray name can be removed by one.
    """
    problems = []
    for correction, source in moved:
        key = _name_key(correction.designator)
        stray = [
            row
            for row in _names(cursor, source)
            if _name_key(row["common_name"]) == key
        ]
        if not stray:
            continue
        operation = "own_object" if correction.own_object else "same_as"
        left = ", ".join(
            _designator((row["catalog_code"], row["sequence"]))
            for row in _listings(cursor, source)
        )
        found = ", ".join(
            f"{row['common_name']!r} (from {row['origin']})" for row in stray
        )
        problems.append(
            f"{correction.label}: {operation} leaves {left} still named {found};"
            " if that catalog's listing joined through the wrong identification,"
            " correct it too, and if its record only names the designator,"
            " remove the name with names.remove"
        )
    if problems:
        raise CorrectionError(problems)
