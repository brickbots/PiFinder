"""Artificial satellites: element sets, positions, magnitudes and passes.

Element sets come from the CelesTrak "visual" and "stations" groups and from
the user, who can paste them on the web page. Every set is stored as a
three-line TLE, whatever format it arrived in.

Positions use SGP4 through Skyfield. The magnitude estimate uses the standard
magnitude (1000 km range, 90 degrees phase angle) and a diffuse sphere phase
function.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path
from typing import Callable, Iterable, Optional

import numpy as np
import requests
from sgp4 import exporter, omm
from sgp4.api import Satrec, SatrecArray
from skyfield.api import EarthSatellite, wgs84
from skyfield.sgp4lib import TEME

from PiFinder.calc_utils import sf_utils
from PiFinder.download_utils import (
    DownloadResult,
    download_atomic,
)
from PiFinder.utils import astro_data_dir, satellite_data_dir


logger = logging.getLogger("Satellites")

CELESTRAK_GROUP_URL = (
    "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
)
CELESTRAK_CATNR_URL = (
    "https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=tle"
)
CELESTRAK_GROUPS = ("visual", "stations")
USER_FILE_NAME = "user.tle"
USER_MAG_FILE_NAME = "user_mags.json"
SELECTION_FILE_NAME = "selection.json"
STD_MAG_FILE = astro_data_dir / "satellite_std_mags.csv"
# The CelesTrak "visual" group holds the brightest objects. A member without a
# magnitude in the table gets this value.
DEFAULT_STD_MAG = 4.0
# Element sets older than this give positions that are wrong by many degrees.
MAX_ELEMENT_AGE_DAYS = 30.0
# CelesTrak updates the groups a few times a day and asks clients not to
# download them more often than every two hours.
DOWNLOAD_INTERVAL_HOURS = 12.0
# A download that the user asks for is refused when the file is younger.
MIN_FORCED_DOWNLOAD_SECONDS = 5 * 60.0
# The observer is in darkness when the Sun is below this altitude.
DARK_SUN_ALT_DEG = -6.0
PASS_STEP_SECONDS = 10.0
RATE_STEP_SECONDS = 1.0
# The search for the time a satellite sets looks this far ahead.
SET_SEARCH_SECONDS = 2 * 3600.0
SET_STEP_SECONDS = 20.0
UNIX_EPOCH_JD = 2440587.5

_TLE_LINE1 = re.compile(r"^1 [ 0-9A-Z]{5}[A-Z ] ")
_TLE_LINE2 = re.compile(r"^2 [ 0-9A-Z]{5} ")


class ElementParseError(ValueError):
    """The text holds no element set that can be used."""


@dataclass(frozen=True)
class SatElements:
    """One element set, normalized to TLE lines."""

    name: str
    norad_id: int
    line1: str
    line2: str
    source: str = "user"

    @cached_property
    def epoch(self) -> datetime:
        satrec = Satrec.twoline2rv(self.line1, self.line2)
        jd = satrec.jdsatepoch + satrec.jdsatepochF
        return datetime(2000, 1, 1, 12, tzinfo=timezone.utc) + timedelta(
            days=jd - 2451545.0
        )

    def age_days(self, now: datetime) -> float:
        return (now - self.epoch).total_seconds() / 86400.0

    def to_tle(self) -> str:
        return f"{self.name}\n{self.line1}\n{self.line2}\n"

    def to_earth_satellite(self) -> EarthSatellite:
        return EarthSatellite(self.line1, self.line2, self.name, sf_utils.ts)


@dataclass
class SatLook:
    """Where a satellite is, seen from the observer at one time."""

    time: datetime
    ra: float  # degrees, J2000 (ICRS)
    dec: float
    alt: float
    az: float
    range_km: float
    sunlit: bool
    sun_alt: float
    mag: Optional[float]  # None when the satellite is in Earth's shadow
    ra_rate: float = 0.0  # degrees per second
    dec_rate: float = 0.0

    @property
    def visible(self) -> bool:
        return self.alt > 0 and self.sunlit and self.sun_alt < DARK_SUN_ALT_DEG


@dataclass
class SatPass:
    """One pass above the minimum altitude."""

    rise: datetime
    culmination: datetime
    set: datetime
    rise_az: float
    max_alt: float
    max_alt_az: float
    set_az: float
    visible_start: Optional[datetime] = None
    visible_end: Optional[datetime] = None
    min_mag: Optional[float] = None

    @property
    def visible(self) -> bool:
        return self.visible_start is not None

    def to_dict(self) -> dict:
        return {
            "rise": self.rise.isoformat(),
            "culmination": self.culmination.isoformat(),
            "set": self.set.isoformat(),
            "rise_az": round(self.rise_az, 1),
            "max_alt": round(self.max_alt, 1),
            "max_alt_az": round(self.max_alt_az, 1),
            "set_az": round(self.set_az, 1),
            "visible": self.visible,
            "visible_start": (
                self.visible_start.isoformat() if self.visible_start else None
            ),
            "visible_end": self.visible_end.isoformat() if self.visible_end else None,
            "min_mag": None if self.min_mag is None else round(self.min_mag, 1),
        }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def tle_checksum(line: str) -> int:
    total = 0
    for char in line[:68]:
        if char.isdigit():
            total += int(char)
        elif char == "-":
            total += 1
    return total % 10


def _check_tle_lines(line1: str, line2: str) -> None:
    if len(line1) < 69 or len(line2) < 69:
        raise ElementParseError("a TLE line is shorter than 69 characters")
    for line in (line1, line2):
        if line[68].isdigit() and int(line[68]) != tle_checksum(line):
            raise ElementParseError(f"bad checksum in line {line[:1]}")
    if line1[2:7] != line2[2:7]:
        raise ElementParseError("line 1 and line 2 have different catalog numbers")
    try:
        Satrec.twoline2rv(line1, line2)
    except (ValueError, IndexError) as exc:
        raise ElementParseError(f"SGP4 rejects the lines: {exc}") from exc


def _alpha5_to_int(text: str) -> int:
    """Read a catalog number, also in the Alpha-5 form (A0001 = 100001)."""
    text = text.strip()
    if text and text[0].isalpha():
        letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        return (letters.index(text[0].upper()) + 10) * 10000 + int(text[1:])
    return int(text)


def _parse_tle_text(text: str, source: str) -> tuple[list[SatElements], list[str]]:
    lines = [line.rstrip() for line in text.splitlines()]
    lines = [line for line in lines if line.strip()]
    results: list[SatElements] = []
    errors: list[str] = []
    pending_name: Optional[str] = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if _TLE_LINE1.match(line):
            if index + 1 >= len(lines) or not _TLE_LINE2.match(lines[index + 1]):
                errors.append(f"line 1 without line 2: {line[:20]}...")
                index += 1
                pending_name = None
                continue
            line1, line2 = line[:69], lines[index + 1][:69]
            try:
                _check_tle_lines(line1, line2)
                norad = _alpha5_to_int(line1[2:7])
                name = pending_name or f"NORAD {norad}"
                results.append(SatElements(name, norad, line1, line2, source))
            except ElementParseError as exc:
                errors.append(f"{pending_name or line1[2:7]}: {exc}")
            pending_name = None
            index += 2
            continue
        if _TLE_LINE2.match(line):
            errors.append(f"line 2 without line 1: {line[:20]}...")
            index += 1
            continue
        name = line.strip()
        if name.startswith("0 "):
            name = name[2:].strip()
        pending_name = name[:40] or None
        index += 1
    return results, errors


def _omm_to_elements(fields: dict, source: str) -> SatElements:
    fields = {str(k).upper(): v for k, v in fields.items()}
    for key in list(fields):
        value = fields[key]
        if value is None:
            fields.pop(key)
        elif not isinstance(value, str):
            fields[key] = str(value)
    fields.setdefault("CLASSIFICATION_TYPE", "U")
    fields.setdefault("ELEMENT_SET_NO", "999")
    fields.setdefault("REV_AT_EPOCH", "0")
    fields.setdefault("EPHEMERIS_TYPE", "0")
    fields.setdefault("OBJECT_ID", "")
    fields.setdefault("MEAN_MOTION_DOT", "0")
    fields.setdefault("MEAN_MOTION_DDOT", "0")
    fields.setdefault("BSTAR", "0")
    try:
        satrec = Satrec()
        omm.initialize(satrec, fields)
        line1, line2 = exporter.export_tle(satrec)
    except (KeyError, ValueError) as exc:
        raise ElementParseError(f"OMM record is incomplete: {exc}") from exc
    name = fields.get("OBJECT_NAME", "").strip() or f"NORAD {satrec.satnum}"
    _check_tle_lines(line1, line2)
    return SatElements(name[:40], int(satrec.satnum), line1, line2, source)


def _parse_omm_records(
    records: Iterable[dict], source: str
) -> tuple[list[SatElements], list[str]]:
    results: list[SatElements] = []
    errors: list[str] = []
    for record in records:
        try:
            results.append(_omm_to_elements(record, source))
        except ElementParseError as exc:
            errors.append(f"{record.get('OBJECT_NAME', '?')}: {exc}")
    return results, errors


def _parse_kvn(text: str) -> list[dict]:
    records: list[dict] = []
    current: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("COMMENT") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        value = re.sub(r"\s*\[.*\]$", "", value)
        if key == "CCSDS_OMM_VERS" and current:
            records.append(current)
            current = {}
        current[key.upper()] = value
    if current:
        records.append(current)
    return records


def parse_elements(
    text: str, source: str = "user"
) -> tuple[list[SatElements], list[str]]:
    """Read element sets in any common format.

    The formats are: TLE with or without a name line (2LE, 3LE, "0 NAME"),
    and the CCSDS OMM forms that CelesTrak and Space-Track publish: JSON,
    CSV, XML and KVN. Returns the element sets and one message per set that
    could not be read.
    """
    stripped = text.strip().lstrip("﻿")
    if not stripped:
        raise ElementParseError("the text is empty")
    try:
        if stripped[0] in "[{":
            data = json.loads(stripped)
            records = data if isinstance(data, list) else [data]
            results, errors = _parse_omm_records(records, source)
        elif stripped.startswith("<"):
            results, errors = _parse_omm_records(
                omm.parse_xml(io.StringIO(stripped)), source
            )
        elif "CCSDS_OMM_VERS" in stripped or re.search(
            r"^\s*MEAN_MOTION\s*=", stripped, re.M
        ):
            results, errors = _parse_omm_records(_parse_kvn(stripped), source)
        elif stripped.split("\n", 1)[0].upper().startswith("OBJECT_NAME,") or (
            "NORAD_CAT_ID" in stripped.split("\n", 1)[0].upper()
            and "," in stripped.split("\n", 1)[0]
        ):
            reader = csv.DictReader(io.StringIO(stripped))
            results, errors = _parse_omm_records(reader, source)
        else:
            results, errors = _parse_tle_text(stripped, source)
    except (json.JSONDecodeError, SyntaxError) as exc:
        raise ElementParseError(f"the text is not valid JSON or XML: {exc}") from exc
    except Exception as exc:  # the sgp4 XML reader raises many types
        if isinstance(exc, ElementParseError):
            raise
        raise ElementParseError(f"cannot read the text: {exc}") from exc
    if not results and not errors:
        raise ElementParseError("no element set found in the text")
    return results, errors


# ---------------------------------------------------------------------------
# Storage and downloads
# ---------------------------------------------------------------------------


def group_file(group: str, directory: Path = satellite_data_dir) -> Path:
    return directory / f"{group}.tle"


def user_file(directory: Path = satellite_data_dir) -> Path:
    return directory / USER_FILE_NAME


def pass_cache_file(directory: Path = satellite_data_dir) -> Path:
    return directory / "passes.json"


def read_pass_cache(directory: Path = satellite_data_dir) -> Optional[dict]:
    try:
        return json.loads(pass_cache_file(directory).read_text())
    except (OSError, ValueError):
        return None


def _validate_tle_file(path: Path) -> None:
    results, _errors = parse_elements(path.read_text(errors="replace"), "celestrak")
    if not results:
        raise ValueError("the file holds no valid TLE")


def download_group(
    group: str,
    directory: Path = satellite_data_dir,
    progress_callback: Optional[Callable[[Optional[int]], None]] = None,
) -> DownloadResult:
    return download_atomic(
        CELESTRAK_GROUP_URL.format(group=group),
        group_file(group, directory),
        progress_callback=progress_callback,
        validator=_validate_tle_file,
    )


def group_download_needed(
    group: str, now: datetime, directory: Path = satellite_data_dir
) -> tuple[bool, str]:
    """CelesTrak sends no Last-Modified, so the file age decides."""
    path = group_file(group, directory)
    if not path.exists():
        return True, "no existing file"
    age_hours = (now.timestamp() - path.stat().st_mtime) / 3600.0
    if age_hours > DOWNLOAD_INTERVAL_HOURS:
        return True, f"file is {age_hours:.0f} hours old"
    return False, "file is recent"


@dataclass(frozen=True)
class GroupRefresh:
    """The result of one request to download the CelesTrak groups.

    ``status`` is "downloaded", "current" (no file was old enough), "busy"
    (another download runs), "too_soon" or "failed".
    """

    status: str
    failed: tuple[str, ...] = ()
    wait_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in ("downloaded", "current")


_download_lock = threading.Lock()


def forced_download_wait(
    now: datetime, directory: Path = satellite_data_dir
) -> dict[str, float]:
    """Seconds until a forced download of each group is permitted."""
    waits: dict[str, float] = {}
    for group in CELESTRAK_GROUPS:
        path = group_file(group, directory)
        age = now.timestamp() - path.stat().st_mtime if path.exists() else None
        # A file from the future means the clock changed: permit the download.
        if age is None or age < 0:
            waits[group] = 0.0
        else:
            waits[group] = max(0.0, MIN_FORCED_DOWNLOAD_SECONDS - age)
    return waits


def refresh_groups(
    now: datetime,
    force: bool = False,
    directory: Path = satellite_data_dir,
    progress_callback: Optional[Callable[[Optional[int]], None]] = None,
    on_start: Optional[Callable[[], None]] = None,
) -> GroupRefresh:
    """Download the groups that need it. Only one download runs at a time.

    Without ``force`` the file age decides. With ``force`` each group
    downloads, except a group that downloaded a few minutes ago.
    """
    if not _download_lock.acquire(blocking=False):
        return GroupRefresh("busy")
    try:
        waits = forced_download_wait(now, directory)
        wanted = []
        for group in CELESTRAK_GROUPS:
            needed, reason = group_download_needed(group, now, directory)
            if needed or (force and waits[group] <= 0):
                logger.info("Satellite group %s: %s", group, reason)
                wanted.append(group)
        if not wanted:
            if force:
                return GroupRefresh("too_soon", wait_seconds=min(waits.values()))
            return GroupRefresh("current")
        if on_start is not None:
            on_start()
        failed = tuple(
            group
            for group in wanted
            if not download_group(group, directory, progress_callback).success
        )
        return GroupRefresh("failed" if failed else "downloaded", failed)
    finally:
        _download_lock.release()


def fetch_by_norad(norad: int) -> list[SatElements]:
    """Get the current element set of one object from CelesTrak."""
    response = requests.get(CELESTRAK_CATNR_URL.format(norad=int(norad)), timeout=15)
    response.raise_for_status()
    if "No GP data found" in response.text:
        raise ElementParseError(f"CelesTrak has no elements for NORAD {norad}")
    results, _errors = parse_elements(response.text, "user")
    if not results:
        raise ElementParseError(f"CelesTrak has no elements for NORAD {norad}")
    return results


_user_file_lock = threading.Lock()


def read_tle_file(path: Path, source: str) -> list[SatElements]:
    if not path.exists():
        return []
    try:
        results, errors = parse_elements(path.read_text(errors="replace"), source)
    except ElementParseError:
        return []
    for message in errors:
        logger.warning("%s: %s", path.name, message)
    return results


def load_user_elements(directory: Path = satellite_data_dir) -> list[SatElements]:
    return read_tle_file(user_file(directory), "user")


def save_user_elements(
    new: Iterable[SatElements], directory: Path = satellite_data_dir
) -> list[SatElements]:
    """Add or replace user element sets, keyed by NORAD id."""
    with _user_file_lock:
        by_id = {e.norad_id: e for e in load_user_elements(directory)}
        for element in new:
            by_id[element.norad_id] = SatElements(
                element.name, element.norad_id, element.line1, element.line2, "user"
            )
        _write_user_file(list(by_id.values()), directory)
        return list(by_id.values())


def delete_user_element(norad_id: int, directory: Path = satellite_data_dir) -> bool:
    """Remove a user element set, its magnitude and its selection entry."""
    with _user_file_lock:
        current = load_user_elements(directory)
        kept = [e for e in current if e.norad_id != norad_id]
        if len(kept) == len(current):
            return False
        _write_user_file(kept, directory)
        mags = load_user_mags(directory)
        if mags.pop(norad_id, None) is not None:
            _write_json(user_mag_file(directory), {str(k): v for k, v in mags.items()})
        selection = load_selection(directory)
        if norad_id in selection.disabled_user:
            _write_selection(
                Selection(
                    selection.disabled_groups, selection.disabled_user - {norad_id}
                ),
                directory,
            )
        return True


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text)
    temporary.replace(path)


def _write_json(path: Path, data: dict) -> None:
    _write_text(path, json.dumps(data))


def _write_user_file(elements: list[SatElements], directory: Path) -> None:
    _write_text(user_file(directory), "".join(e.to_tle() for e in elements))


@dataclass(frozen=True)
class Selection:
    """The groups and user satellites that the user disabled.

    A disabled item stays stored. It is not in the device catalog and not
    in the pass lists.
    """

    disabled_groups: frozenset[str] = frozenset()
    disabled_user: frozenset[int] = frozenset()

    def group_enabled(self, group: str) -> bool:
        return group not in self.disabled_groups

    def user_enabled(self, norad_id: int) -> bool:
        return norad_id not in self.disabled_user


def selection_file(directory: Path = satellite_data_dir) -> Path:
    return directory / SELECTION_FILE_NAME


def load_selection(directory: Path = satellite_data_dir) -> Selection:
    try:
        data = json.loads(selection_file(directory).read_text())
        return Selection(
            frozenset(str(group) for group in data.get("disabled_groups", [])),
            frozenset(int(norad) for norad in data.get("disabled_user", [])),
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return Selection()


def _write_selection(selection: Selection, directory: Path) -> None:
    _write_json(
        selection_file(directory),
        {
            "disabled_groups": sorted(selection.disabled_groups),
            "disabled_user": sorted(selection.disabled_user),
        },
    )


def set_group_enabled(
    group: str, enabled: bool, directory: Path = satellite_data_dir
) -> None:
    if group not in CELESTRAK_GROUPS:
        raise ValueError(f"unknown group: {group}")
    with _user_file_lock:
        selection = load_selection(directory)
        groups = selection.disabled_groups - {group}
        if not enabled:
            groups = groups | {group}
        _write_selection(Selection(groups, selection.disabled_user), directory)


def set_user_enabled(
    norad_id: int, enabled: bool, directory: Path = satellite_data_dir
) -> None:
    with _user_file_lock:
        selection = load_selection(directory)
        user = selection.disabled_user - {norad_id}
        if not enabled:
            user = user | {norad_id}
        _write_selection(Selection(selection.disabled_groups, user), directory)


def load_all_elements(
    now: datetime,
    directory: Path = satellite_data_dir,
    groups: Iterable[str] = CELESTRAK_GROUPS,
    include_disabled: bool = False,
) -> list[SatElements]:
    """All element sets, one per NORAD id, without sets that are too old.

    A user set replaces a downloaded set of the same object only if it is
    newer, so a pasted TLE does not stay in use after CelesTrak has a fresh one.
    Groups and user sets that the user disabled are left out, unless
    ``include_disabled`` is set.
    """
    selection = Selection() if include_disabled else load_selection(directory)
    by_id: dict[int, SatElements] = {}
    for group in groups:
        if not selection.group_enabled(group):
            continue
        for element in read_tle_file(group_file(group, directory), "celestrak"):
            by_id.setdefault(element.norad_id, element)
    for element in load_user_elements(directory):
        if not selection.user_enabled(element.norad_id):
            continue
        existing = by_id.get(element.norad_id)
        if existing is None or element.epoch > existing.epoch:
            by_id[element.norad_id] = element
    return [e for e in by_id.values() if abs(e.age_days(now)) <= MAX_ELEMENT_AGE_DAYS]


_std_mags: Optional[dict[int, float]] = None


def user_mag_file(directory: Path = satellite_data_dir) -> Path:
    return directory / USER_MAG_FILE_NAME


def load_user_mags(directory: Path = satellite_data_dir) -> dict[int, float]:
    try:
        data = json.loads(user_mag_file(directory).read_text())
        return {int(key): float(value) for key, value in data.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def save_user_mag(
    norad_id: int, std_mag: Optional[float], directory: Path = satellite_data_dir
) -> None:
    """Set or clear the standard magnitude the user gave for an object."""
    with _user_file_lock:
        mags = load_user_mags(directory)
        if std_mag is None:
            mags.pop(norad_id, None)
        else:
            mags[norad_id] = float(std_mag)
        _write_json(user_mag_file(directory), {str(k): v for k, v in mags.items()})


def std_magnitude(norad_id: int, user_mags: Optional[dict[int, float]] = None) -> float:
    """The magnitude the user gave, else the table value, else the default."""
    if user_mags and norad_id in user_mags:
        return user_mags[norad_id]
    global _std_mags
    if _std_mags is None:
        table: dict[int, float] = {}
        try:
            with STD_MAG_FILE.open() as source:
                for line in source:
                    if line.startswith("#") or "," not in line:
                        continue
                    key, value = line.split(",", 1)
                    table[int(key)] = float(value)
        except OSError as exc:
            logger.warning("No satellite magnitude table: %s", exc)
        _std_mags = table
    return _std_mags.get(norad_id, DEFAULT_STD_MAG)


# ---------------------------------------------------------------------------
# Positions and magnitudes
# ---------------------------------------------------------------------------


def phase_function(phase_angle_deg: float) -> float:
    """Diffuse sphere brightness relative to full phase (1.0 at 0 degrees)."""
    phi = math.radians(phase_angle_deg)
    return ((math.pi - phi) * math.cos(phi) + math.sin(phi)) / math.pi


def apparent_magnitude(
    std_mag: float, range_km: float, phase_angle_deg: float
) -> float:
    """Magnitude from the standard magnitude at 1000 km and 90 degrees phase."""
    relative = phase_function(phase_angle_deg) / phase_function(90.0)
    relative = max(relative, 1e-4)
    return std_mag + 5.0 * math.log10(range_km / 1000.0) - 2.5 * math.log10(relative)


@dataclass
class TrackedSatellite:
    """An element set with its Skyfield satellite, ready for many positions."""

    elements: SatElements
    std_mag: float
    satellite: EarthSatellite = field(repr=False)

    @classmethod
    def from_elements(
        cls, elements: SatElements, user_mags: Optional[dict[int, float]] = None
    ) -> "TrackedSatellite":
        return cls(
            elements,
            std_magnitude(elements.norad_id, user_mags),
            elements.to_earth_satellite(),
        )

    @property
    def name(self) -> str:
        return self.elements.name

    @property
    def norad_id(self) -> int:
        return self.elements.norad_id


def observer_topos(lat: float, lon: float, altitude_m: float):
    return wgs84.latlon(lat, lon, altitude_m)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


EARTH_RADIUS_KM = 6371.0


@dataclass
class SunContext:
    """The Sun for one time and observer, shared by many satellites."""

    t: object  # Skyfield Time
    sun_geocentric_km: np.ndarray
    sun_alt: float


def sun_context(topos, dt: datetime) -> SunContext:
    t = sf_utils.ts.from_datetime(_as_utc(dt))
    earth = sf_utils.eph["earth"]
    sun = sf_utils.eph["sun"]
    sun_geocentric = sun.at(t).position.km - earth.at(t).position.km
    sun_alt = (earth + topos).at(t).observe(sun).apparent().altaz()[0].degrees
    return SunContext(t, np.asarray(sun_geocentric), float(sun_alt))


def in_sunlight(sat_km: np.ndarray, sun_km: np.ndarray) -> np.ndarray:
    """Cylindrical shadow model: dark when behind the Earth and inside its
    radius. Works on one vector (3,) or many (3, n)."""
    if sat_km.ndim == 2 and sun_km.ndim == 1:
        sun_km = sun_km[:, np.newaxis]
    sun_hat = sun_km / np.linalg.norm(sun_km, axis=0)
    along = np.sum(sat_km * sun_hat, axis=0)
    across = np.linalg.norm(sat_km - along * sun_hat, axis=0)
    return (along > 0) | (across > EARTH_RADIUS_KM)


def phase_angle_deg(
    sat_km: np.ndarray, sun_km: np.ndarray, observer_km: np.ndarray
) -> np.ndarray:
    to_sun = sun_km - sat_km
    to_observer = observer_km - sat_km
    cos_phase = np.sum(to_sun * to_observer, axis=0) / (
        np.linalg.norm(to_sun, axis=0) * np.linalg.norm(to_observer, axis=0)
    )
    return np.degrees(np.arccos(np.clip(cos_phase, -1.0, 1.0)))


def look(
    sat: TrackedSatellite,
    topos,
    dt: datetime,
    with_rates: bool = True,
    sun: Optional[SunContext] = None,
) -> SatLook:
    """Position, brightness and motion of a satellite at ``dt``.

    Give ``sun`` from ``sun_context`` when many satellites share one time.
    """
    dt = _as_utc(dt)
    if sun is None:
        sun = sun_context(topos, dt)
    t = sun.t
    difference = sat.satellite - topos
    topocentric = difference.at(t)
    alt, az, distance = topocentric.altaz()
    ra, dec, _ = topocentric.radec()
    sat_km = sat.satellite.at(t).position.km
    sunlit = bool(in_sunlight(sat_km, sun.sun_geocentric_km))
    range_km = float(distance.km)
    mag: Optional[float] = None
    if sunlit:
        phase = float(
            phase_angle_deg(sat_km, sun.sun_geocentric_km, topos.at(t).position.km)
        )
        mag = apparent_magnitude(sat.std_mag, range_km, phase)

    ra_rate = dec_rate = 0.0
    if with_rates:
        later = sf_utils.ts.from_datetime(dt + timedelta(seconds=RATE_STEP_SECONDS))
        ra2, dec2, _ = difference.at(later).radec()
        ra_step = (ra2._degrees - ra._degrees + 540.0) % 360.0 - 180.0
        ra_rate = float(ra_step / RATE_STEP_SECONDS)
        dec_rate = float((dec2.degrees - dec.degrees) / RATE_STEP_SECONDS)
    return SatLook(
        time=dt,
        ra=float(ra._degrees),
        dec=float(dec.degrees),
        alt=float(alt.degrees),
        az=float(az.degrees),
        range_km=range_km,
        sunlit=sunlit,
        sun_alt=sun.sun_alt,
        mag=mag,
        ra_rate=ra_rate,
        dec_rate=dec_rate,
    )


def _magnitudes(std_mag, range_km, phase_deg) -> np.ndarray:
    """``apparent_magnitude`` for arrays."""
    phi = np.radians(phase_deg)
    relative = (
        ((np.pi - phi) * np.cos(phi) + np.sin(phi)) / np.pi / phase_function(90.0)
    )
    return (
        std_mag
        + 5.0 * np.log10(np.asarray(range_km) / 1000.0)
        - 2.5 * np.log10(np.maximum(relative, 1e-4))
    )


def _geometry_many(sats: list[TrackedSatellite], topos, times: list[datetime]):
    """Positions of n satellites at m times with one SGP4 call.

    Returns the Skyfield times, the geocentric positions in km (3, n, m),
    the positions relative to the observer in km (3, n, m), the altitude
    and the azimuth in degrees (n, m). A satellite that SGP4 cannot
    propagate gets NaN.
    """
    t = sf_utils.ts.from_datetimes(times)
    days = np.array([dt.timestamp() for dt in times]) / 86400.0
    whole = np.floor(days)
    _errors, teme_km, _velocity = SatrecArray(
        [sat.satellite.model for sat in sats]
    ).sgp4(whole + UNIX_EPOCH_JD, days - whole)
    # The rotation matrix goes from GCRS to TEME: use its transpose.
    sat_km = np.einsum("jim,nmj->inm", TEME.rotation_at(t), teme_km)
    relative_km = sat_km - topos.at(t).position.km[:, np.newaxis, :]
    horizon = np.einsum("ijm,jnm->inm", topos.rotation_at(t), relative_km)
    range_km = np.linalg.norm(relative_km, axis=0)
    alt = np.degrees(np.arcsin(horizon[2] / range_km))
    az = np.degrees(np.arctan2(horizon[1], horizon[0])) % 360.0
    return t, sat_km, relative_km, alt, az


def look_many(
    sats: list[TrackedSatellite],
    topos,
    dt: datetime,
    sun: Optional[SunContext] = None,
) -> list[SatLook]:
    """``look`` without rates for many satellites at one time.

    One vectorized SGP4 call replaces a Skyfield call per satellite.
    """
    if not sats:
        return []
    dt = _as_utc(dt)
    if sun is None:
        sun = sun_context(topos, dt)
    t, sat_km, relative_km, alt, az = _geometry_many(sats, topos, [dt])
    sat_km, relative_km = sat_km[:, :, 0], relative_km[:, :, 0]
    range_km = np.linalg.norm(relative_km, axis=0)
    ra = np.degrees(np.arctan2(relative_km[1], relative_km[0])) % 360.0
    dec = np.degrees(np.arcsin(relative_km[2] / range_km))
    sun_km = sun.sun_geocentric_km[:, np.newaxis]
    sunlit = in_sunlight(sat_km, sun_km)
    phase = phase_angle_deg(sat_km, sun_km, topos.at(t).position.km)
    mags = _magnitudes(np.array([sat.std_mag for sat in sats]), range_km, phase)
    return [
        SatLook(
            time=dt,
            ra=float(ra[i]),
            dec=float(dec[i]),
            alt=float(alt[i, 0]),
            az=float(az[i, 0]),
            range_km=float(range_km[i]),
            sunlit=bool(sunlit[i]),
            sun_alt=sun.sun_alt,
            mag=float(mags[i]) if sunlit[i] else None,
        )
        for i in range(len(sats))
    ]


def seconds_until_set(
    sats: list[TrackedSatellite],
    topos,
    dt: datetime,
    search_seconds: float = SET_SEARCH_SECONDS,
    step_seconds: float = SET_STEP_SECONDS,
) -> list[Optional[float]]:
    """For each satellite: the seconds until it goes below the horizon.

    None when the satellite is below the horizon at ``dt``, or stays up for
    the full search time (a geostationary satellite, for example).
    """
    if not sats:
        return []
    dt = _as_utc(dt)
    offsets = np.arange(0.0, search_seconds + step_seconds, step_seconds)
    times = [dt + timedelta(seconds=float(offset)) for offset in offsets]
    alt = _geometry_many(sats, topos, times)[3]
    result: list[Optional[float]] = []
    for row in alt:
        down = np.flatnonzero(~(row > 0))
        if len(down) == 0 or down[0] == 0:
            result.append(None)
            continue
        after = int(down[0])
        above, below = row[after - 1], row[after]
        # The altitude is close to linear over one step near the horizon.
        part = above / (above - below) if np.isfinite(below) else 0.0
        result.append(float(offsets[after - 1] + part * step_seconds))
    return result


def radec_at(sat: TrackedSatellite, topos, dt: datetime) -> tuple[float, float]:
    """J2000 RA/Dec in degrees only: cheap enough for every UI frame."""
    t = sf_utils.ts.from_datetime(_as_utc(dt))
    ra, dec, _ = (sat.satellite - topos).at(t).radec()
    return float(ra._degrees), float(dec.degrees)


def find_passes(
    sat: TrackedSatellite,
    topos,
    start: datetime,
    hours: float = 24.0,
    min_alt: float = 10.0,
) -> list[SatPass]:
    """Passes above ``min_alt`` between ``start`` and ``start + hours``.

    A pass is visible when, for at least one sample, the satellite is in
    sunlight and the Sun is below DARK_SUN_ALT_DEG for the observer.
    """
    ts = sf_utils.ts
    start = _as_utc(start)
    t0 = ts.from_datetime(start)
    t1 = ts.from_datetime(start + timedelta(hours=hours))
    times, events = sat.satellite.find_events(topos, t0, t1, altitude_degrees=min_alt)
    difference = sat.satellite - topos

    passes: list[SatPass] = []
    rise = culmination = None
    for t, event in zip(times, events):
        if event == 0:
            rise, culmination = t, None
        elif event == 1:
            if rise is None:
                rise = t0
            culmination = t
        elif event == 2 and rise is not None:
            if culmination is None:
                culmination = rise
            passes.append(_describe_pass(sat, topos, difference, rise, culmination, t))
            rise = culmination = None
    if rise is not None and culmination is not None:
        passes.append(_describe_pass(sat, topos, difference, rise, culmination, t1))
    return passes


def _describe_pass(sat, topos, difference, rise, culmination, set_time) -> SatPass:
    ts = sf_utils.ts
    duration = max((set_time.tt - rise.tt) * 86400.0, 1.0)
    count = max(2, int(duration / PASS_STEP_SECONDS) + 1)
    samples = ts.tt_jd(np.linspace(rise.tt, set_time.tt, count))
    topocentric = difference.at(samples)
    alt, az, distance = topocentric.altaz()
    earth = sf_utils.eph["earth"]
    sun = sf_utils.eph["sun"]
    sun_alt = (earth + topos).at(samples).observe(sun).apparent().altaz()[0].degrees
    sun_km = sun.at(samples).position.km - earth.at(samples).position.km
    sat_km = sat.satellite.at(samples).position.km
    sunlit = in_sunlight(sat_km, sun_km)
    phase = phase_angle_deg(sat_km, sun_km, topos.at(samples).position.km)
    mags = _magnitudes(sat.std_mag, distance.km, phase)
    visible = np.asarray(sunlit) & (sun_alt < DARK_SUN_ALT_DEG) & (alt.degrees > 0)

    culmination_alt, culmination_az, _ = difference.at(culmination).altaz()
    result = SatPass(
        rise=rise.utc_datetime(),
        culmination=culmination.utc_datetime(),
        set=set_time.utc_datetime(),
        rise_az=float(az.degrees[0]),
        max_alt=float(culmination_alt.degrees),
        max_alt_az=float(culmination_az.degrees),
        set_az=float(az.degrees[-1]),
    )
    if visible.any():
        indices = np.nonzero(visible)[0]
        result.visible_start = samples[int(indices[0])].utc_datetime()
        result.visible_end = samples[int(indices[-1])].utc_datetime()
        result.min_mag = float(np.min(mags[visible]))
    return result


AZ_NAMES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def compass(az: float) -> str:
    return AZ_NAMES[int(((az % 360.0) + 22.5) // 45.0) % 8]
