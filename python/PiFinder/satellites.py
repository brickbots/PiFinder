"""Artificial satellites: element sets, positions, magnitudes and passes.

Element sets come from the CelesTrak groups that the user selects and from
the user, who can paste them on the web page. A mount follow that the user
corrects with the arrow keys stores a corrected set. Every set is stored as a
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
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path
from typing import Callable, Iterable, Optional

import numpy as np
import requests
from sgp4 import exporter, omm
from sgp4.api import Satrec, SatrecArray
from skyfield.api import EarthSatellite, wgs84
from skyfield.framelib import itrs
from skyfield.sgp4lib import TEME, theta_GMST1982

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


@dataclass(frozen=True)
class CelestrakGroup:
    """A CelesTrak GP group that the user can select."""

    name: str  # the GROUP value of the CelesTrak URL
    label: str
    # A large group holds thousands of satellites. A Pi needs a long time to
    # predict their passes.
    large: bool = False


# The CelesTrak groups that the user can select. The names are the GROUP
# values of the CelesTrak GP page. The large groups are at the end. They are
# not selected by default. CelesTrak has no "noaa" and "goes" groups. Their
# satellites are in "weather".
AVAILABLE_GROUPS = (
    CelestrakGroup("visual", "Brightest"),
    CelestrakGroup("stations", "Space stations"),
    CelestrakGroup("last-30-days", "Launched in the last 30 days"),
    CelestrakGroup("amateur", "Amateur radio"),
    CelestrakGroup("cubesat", "CubeSats"),
    CelestrakGroup("education", "Education"),
    CelestrakGroup("engineering", "Engineering"),
    CelestrakGroup("science", "Science"),
    CelestrakGroup("geodetic", "Geodetic"),
    CelestrakGroup("weather", "Weather"),
    CelestrakGroup("resource", "Earth resources"),
    CelestrakGroup("planet", "Planet"),
    CelestrakGroup("spire", "Spire"),
    CelestrakGroup("radar", "Radar calibration"),
    CelestrakGroup("sarsat", "Search and rescue"),
    CelestrakGroup("military", "Military"),
    CelestrakGroup("iridium-NEXT", "Iridium NEXT"),
    CelestrakGroup("gps-ops", "GPS"),
    CelestrakGroup("galileo", "Galileo"),
    CelestrakGroup("glo-ops", "GLONASS"),
    CelestrakGroup("beidou", "BeiDou"),
    CelestrakGroup("geo", "Geostationary"),
    CelestrakGroup("oneweb", "OneWeb", large=True),
    CelestrakGroup("kuiper", "Kuiper", large=True),
    CelestrakGroup("starlink", "Starlink", large=True),
    CelestrakGroup("active", "All active satellites", large=True),
)
CELESTRAK_GROUPS = tuple(group.name for group in AVAILABLE_GROUPS)
# The groups that a PiFinder without a stored selection uses.
DEFAULT_GROUPS = ("visual", "stations")
USER_FILE_NAME = "user.tle"
CORRECTED_FILE_NAME = "corrected.tle"
# The text between the name and the time in the name of a corrected set.
CORRECTED_MARK = " corr "
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
# A long pass, of a high orbit, gets at most this many samples.
PASS_MAX_SAMPLES = 400
# The coarse step of the pass search is this fraction of the orbit. The
# search of Skyfield's find_events uses the same step.
PASS_GRID_ORBIT_FRACTION = 0.05
PASS_GRID_MIN_SECONDS = 20.0
PASS_GRID_MAX_SECONDS = 1800.0
# A grid point that is a local maximum gets a refined search when it is
# above min_alt minus this margin. The true peak can be higher than the
# grid point. On the CelesTrak "active" group it was less than 5 degrees
# higher.
PASS_PEAK_MARGIN_DEG = 20.0
# The pass search keeps at most this many satellite times in memory at once.
PASS_CHUNK_SAMPLES = 100_000
PASS_TIME_TOLERANCE_SECONDS = 0.5
# The pass search interpolates the Sun linearly between points this far apart.
SUN_GRID_SECONDS = 300.0
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


def corrected_file(directory: Path = satellite_data_dir) -> Path:
    return directory / CORRECTED_FILE_NAME


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
    """The result of one request to download CelesTrak groups.

    ``status`` is "downloaded", "current" (no file was old enough),
    "no_groups" (no group is selected), "busy" (another download runs),
    "too_soon" (each group downloaded a few minutes ago) or "failed".
    ``refused`` holds each group that downloaded a few minutes ago, with
    the seconds until a forced download is permitted.
    """

    status: str
    failed: tuple[str, ...] = ()
    wait_seconds: float = 0.0
    downloaded: tuple[str, ...] = ()
    refused: tuple[tuple[str, float], ...] = ()

    @property
    def ok(self) -> bool:
        return self.status in ("downloaded", "current", "no_groups")


_download_lock = threading.Lock()


def forced_download_wait(
    now: datetime,
    directory: Path = satellite_data_dir,
    groups: Optional[Iterable[str]] = None,
) -> dict[str, float]:
    """Seconds until a forced download of each group is permitted.

    Without ``groups`` the selected groups are used.
    """
    if groups is None:
        groups = selected_groups(directory)
    waits: dict[str, float] = {}
    for group in groups:
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
    groups: Optional[Iterable[str]] = None,
) -> GroupRefresh:
    """Download the groups that need it. Only one download runs at a time.

    Without ``groups`` the selected groups are used. Without ``force`` the
    file age decides. With ``force`` each group downloads, except a group
    that downloaded a few minutes ago.
    """
    if not _download_lock.acquire(blocking=False):
        return GroupRefresh("busy")
    try:
        if groups is None:
            groups = selected_groups(directory)
        groups = tuple(groups)
        if not groups:
            return GroupRefresh("no_groups")
        waits = forced_download_wait(now, directory, groups)
        wanted = []
        refused = []
        for group in groups:
            needed, reason = group_download_needed(group, now, directory)
            if needed or (force and waits[group] <= 0):
                logger.info("Satellite group %s: %s", group, reason)
                wanted.append(group)
            elif force:
                refused.append((group, waits[group]))
        wait = min((seconds for _group, seconds in refused), default=0.0)
        if not wanted:
            if force:
                return GroupRefresh(
                    "too_soon", wait_seconds=wait, refused=tuple(refused)
                )
            return GroupRefresh("current")
        if on_start is not None:
            on_start()
        downloaded = []
        failed = []
        for group in wanted:
            if download_group(group, directory, progress_callback).success:
                downloaded.append(group)
            else:
                failed.append(group)
        return GroupRefresh(
            "failed" if failed else "downloaded",
            tuple(failed),
            wait,
            tuple(downloaded),
            tuple(refused),
        )
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
                replace(selection, disabled_user=selection.disabled_user - {norad_id}),
                directory,
            )
        return True


def load_corrected_elements(directory: Path = satellite_data_dir) -> list[SatElements]:
    return read_tle_file(corrected_file(directory), "corrected")


def corrected_name(name: str, when: datetime) -> str:
    """The name of a corrected set: the base name, the mark and the UTC time.

    The mark and the time of an earlier correction are replaced.
    """
    base = name.split(CORRECTED_MARK)[0].strip()
    return f"{base}{CORRECTED_MARK}{_as_utc(when):%Y-%m-%d %H:%M}"


def save_corrected_element(
    element: SatElements, when: datetime, directory: Path = satellite_data_dir
) -> SatElements:
    """Store the corrected set of one satellite. It replaces an earlier
    corrected set of the same NORAD id."""
    corrected = SatElements(
        corrected_name(element.name, when),
        element.norad_id,
        element.line1,
        element.line2,
        "corrected",
    )
    with _user_file_lock:
        by_id = {e.norad_id: e for e in load_corrected_elements(directory)}
        by_id[corrected.norad_id] = corrected
        _write_text(
            corrected_file(directory), "".join(e.to_tle() for e in by_id.values())
        )
    return corrected


def delete_corrected_element(
    norad_id: int, directory: Path = satellite_data_dir
) -> bool:
    """Remove a corrected set and its selection entry."""
    with _user_file_lock:
        current = load_corrected_elements(directory)
        kept = [e for e in current if e.norad_id != norad_id]
        if len(kept) == len(current):
            return False
        _write_text(corrected_file(directory), "".join(e.to_tle() for e in kept))
        selection = load_selection(directory)
        if norad_id in selection.disabled_corrected:
            _write_selection(
                replace(
                    selection,
                    disabled_corrected=selection.disabled_corrected - {norad_id},
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
    """The selected groups, and the user satellites and corrected sets that
    the user disabled.

    The PiFinder downloads, updates and uses only the selected groups. The
    file of a group that is not selected stays on disk, but it is not read.
    A disabled set stays stored. It is not in the device catalog and not in
    the pass lists.
    """

    groups: frozenset[str] = frozenset(DEFAULT_GROUPS)
    disabled_user: frozenset[int] = frozenset()
    disabled_corrected: frozenset[int] = frozenset()

    def group_enabled(self, group: str) -> bool:
        return group in self.groups

    def user_enabled(self, norad_id: int) -> bool:
        return norad_id not in self.disabled_user

    def corrected_enabled(self, norad_id: int) -> bool:
        return norad_id not in self.disabled_corrected


def selection_file(directory: Path = satellite_data_dir) -> Path:
    return directory / SELECTION_FILE_NAME


def load_selection(directory: Path = satellite_data_dir) -> Selection:
    """The stored selection. Group names that are not known are ignored."""
    try:
        data = json.loads(selection_file(directory).read_text())
        groups = frozenset(DEFAULT_GROUPS)
        if "groups" in data:
            groups = frozenset(
                str(group) for group in data["groups"] if group in CELESTRAK_GROUPS
            )
        return Selection(
            groups,
            frozenset(int(norad) for norad in data.get("disabled_user", [])),
            frozenset(int(norad) for norad in data.get("disabled_corrected", [])),
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return Selection()


def selected_groups(directory: Path = satellite_data_dir) -> tuple[str, ...]:
    """The selected groups, in the order of ``AVAILABLE_GROUPS``."""
    selection = load_selection(directory)
    return tuple(group for group in CELESTRAK_GROUPS if selection.group_enabled(group))


def _write_selection(selection: Selection, directory: Path) -> None:
    _write_json(
        selection_file(directory),
        {
            "groups": sorted(selection.groups),
            "disabled_user": sorted(selection.disabled_user),
            "disabled_corrected": sorted(selection.disabled_corrected),
        },
    )


def set_group_enabled(
    group: str, enabled: bool, directory: Path = satellite_data_dir
) -> None:
    """Select a group, or remove it from the selection."""
    if group not in CELESTRAK_GROUPS:
        raise ValueError(f"unknown group: {group}")
    with _user_file_lock:
        selection = load_selection(directory)
        groups = selection.groups - {group}
        if enabled:
            groups = groups | {group}
        _write_selection(replace(selection, groups=groups), directory)


def set_user_enabled(
    norad_id: int, enabled: bool, directory: Path = satellite_data_dir
) -> None:
    with _user_file_lock:
        selection = load_selection(directory)
        user = selection.disabled_user - {norad_id}
        if not enabled:
            user = user | {norad_id}
        _write_selection(replace(selection, disabled_user=user), directory)


def set_corrected_enabled(
    norad_id: int, enabled: bool, directory: Path = satellite_data_dir
) -> None:
    with _user_file_lock:
        selection = load_selection(directory)
        corrected = selection.disabled_corrected - {norad_id}
        if not enabled:
            corrected = corrected | {norad_id}
        _write_selection(replace(selection, disabled_corrected=corrected), directory)


def load_all_elements(
    now: datetime,
    directory: Path = satellite_data_dir,
    groups: Iterable[str] = CELESTRAK_GROUPS,
    include_disabled: bool = False,
) -> list[SatElements]:
    """All element sets, one per NORAD id, without sets that are too old.

    A user set replaces a downloaded set of the same object only if it is
    newer, so a pasted TLE does not stay in use after CelesTrak has a fresh one.
    A corrected set keeps the epoch of the set it corrects. It replaces a set
    of the same epoch or older, so a newer download replaces the correction.
    Groups that are not selected and sets that the user disabled are left
    out, unless ``include_disabled`` is set. Then each group file on disk
    is read.
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
    for element in load_corrected_elements(directory):
        if not selection.corrected_enabled(element.norad_id):
            continue
        existing = by_id.get(element.norad_id)
        if existing is None or element.epoch >= existing.epoch:
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

    See ``find_passes_many``, which does the work.
    """
    return find_passes_many([sat], topos, start, hours, min_alt)[0]


def find_passes_many(
    sats: list[TrackedSatellite],
    topos,
    start: datetime,
    hours: float = 24.0,
    min_alt: float = 10.0,
) -> list[list[SatPass]]:
    """For each satellite: its passes above ``min_alt`` in the window from
    ``start`` to ``start + hours``.

    A pass is an interval of the window in which the satellite is above
    ``min_alt``. A pass that is in progress at the start or at the end of
    the window starts or ends there, and its culmination is the highest
    point inside the window. A satellite that stays above ``min_alt`` has
    one pass for the full window.

    A pass is visible when, for at least one sample, the satellite is in
    sunlight and the Sun is below DARK_SUN_ALT_DEG for the observer.

    The search propagates the satellites in chunks on a coarse time grid
    with one SGP4 call per chunk. It interpolates between the grid points
    with the SGP4 velocities, and finds the culminations, the rises and
    the sets on that curve. A satellite that SGP4 cannot propagate over
    the full window gets no passes.
    """
    result: list[list[SatPass]] = [[] for _sat in sats]
    span = hours * 3600.0
    if not sats or span <= 0:
        return result
    frame = _PassFrame.create(topos, _as_utc(start), span)
    steps = np.array([_grid_step_seconds(sat.satellite.model) for sat in sats])
    order = np.argsort(steps, kind="stable")
    failed: list[str] = []
    position = 0
    while position < len(order):
        # The steps are in ascending order, so the first is the smallest.
        count = int(math.ceil(span / steps[order[position]])) + 1
        size = max(1, PASS_CHUNK_SAMPLES // count)
        chunk = order[position : position + size]
        position += size
        chunk_passes = _chunk_passes(
            [sats[i] for i in chunk], frame, count, min_alt, failed
        )
        for index, passes in zip(chunk, chunk_passes):
            result[index] = passes
    if failed:
        logger.warning(
            "No passes for %d satellites that SGP4 cannot propagate: %s",
            len(failed),
            ", ".join(failed[:5]) + (" ..." if len(failed) > 5 else ""),
        )
    return result


def _grid_step_seconds(model: Satrec) -> float:
    """The coarse step of the pass search for one satellite.

    It is a fraction of the orbit. For an eccentric orbit it is shorter, by
    the ratio of the angular rate at perigee to the mean angular rate.
    """
    if not model.no_kozai > 0:
        return PASS_GRID_MAX_SECONDS
    period = 2.0 * math.pi / model.no_kozai * 60.0
    ecc = min(max(model.ecco, 0.0), 0.99)
    perigee_rate = (1.0 + ecc) ** 2 / (1.0 - ecc**2) ** 1.5
    step = PASS_GRID_ORBIT_FRACTION * period / perigee_rate
    return min(max(step, PASS_GRID_MIN_SECONDS), PASS_GRID_MAX_SECONDS)


@dataclass
class _PassFrame:
    """The observer, the Earth rotation and the Sun for one pass search.

    All positions are Earth-fixed and in km. Times are seconds after the
    start of the window.
    """

    start: datetime
    span: float
    observer_km: np.ndarray  # (3,)
    up: np.ndarray  # (3,) unit vectors of the observer's horizon frame
    north: np.ndarray
    east: np.ndarray
    theta0: float  # Greenwich mean sidereal angle (GMST 1982) at the start
    theta_rate: float  # radians per second
    sun_seconds: np.ndarray  # (g,)
    sun_km: np.ndarray  # (g, 3)
    sun_alt: np.ndarray  # (g,) degrees, as seen by the observer

    @classmethod
    def create(cls, topos, start: datetime, span: float) -> "_PassFrame":
        ts = sf_utils.ts
        t0 = ts.from_datetime(start)
        theta0, theta_rate = theta_GMST1982(t0.whole, t0.ut1_fraction)
        lat = topos.latitude.radians
        lon = topos.longitude.radians
        up = np.array(
            [
                math.cos(lat) * math.cos(lon),
                math.cos(lat) * math.sin(lon),
                math.sin(lat),
            ]
        )
        north = np.array(
            [
                -math.sin(lat) * math.cos(lon),
                -math.sin(lat) * math.sin(lon),
                math.cos(lat),
            ]
        )
        east = np.array([-math.sin(lon), math.cos(lon), 0.0])

        count = int(math.ceil(span / SUN_GRID_SECONDS)) + 1
        sun_seconds = np.linspace(0.0, span, count)
        t = ts.tt_jd(t0.tt + sun_seconds / 86400.0)
        earth = sf_utils.eph["earth"]
        sun = sf_utils.eph["sun"]
        sun_gcrs = sun.at(t).position.km - earth.at(t).position.km
        sun_km = np.einsum("ijg,jg->gi", itrs.rotation_at(t), sun_gcrs)
        sun_alt = (earth + topos).at(t).observe(sun).apparent().altaz()[0].degrees
        return cls(
            start=start,
            span=span,
            observer_km=np.asarray(topos.itrs_xyz.km, dtype=float),
            up=up,
            north=north,
            east=east,
            theta0=float(theta0),
            theta_rate=float(theta_rate) / 86400.0,
            sun_seconds=sun_seconds,
            sun_km=sun_km,
            sun_alt=np.asarray(sun_alt, dtype=float),
        )

    def sgp4_dates(self, seconds: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The UTC Julian dates of ``seconds``, as SGP4 wants them."""
        days = (self.start.timestamp() + seconds) / 86400.0
        whole = np.floor(days)
        return whole + UNIX_EPOCH_JD, days - whole

    def earth_fixed(self, teme_km: np.ndarray, seconds: np.ndarray) -> np.ndarray:
        """TEME positions (..., 3) at ``seconds`` (...) in the Earth frame."""
        theta = self.theta0 + self.theta_rate * seconds
        cos, sin = np.cos(theta), np.sin(theta)
        x, y = teme_km[..., 0], teme_km[..., 1]
        return np.stack((cos * x + sin * y, cos * y - sin * x, teme_km[..., 2]), -1)

    def altitude(self, sat_km: np.ndarray) -> np.ndarray:
        relative = sat_km - self.observer_km
        return np.degrees(
            np.arcsin(relative @ self.up / np.linalg.norm(relative, axis=-1))
        )

    def horizon(self, sat_km: np.ndarray):
        """Altitude and azimuth in degrees, and the range in km."""
        relative = sat_km - self.observer_km
        range_km = np.linalg.norm(relative, axis=-1)
        alt = np.degrees(np.arcsin(relative @ self.up / range_km))
        az = np.degrees(np.arctan2(relative @ self.east, relative @ self.north))
        return alt, az % 360.0, range_km

    def min_sun_alt(self, low: np.ndarray, high: np.ndarray) -> np.ndarray:
        """The lowest Sun altitude between ``low`` and ``high``.

        The Sun altitude is linear between the grid points, so the lowest
        value is at an end or at a grid point between them.
        """
        lowest = np.minimum(
            np.interp(low, self.sun_seconds, self.sun_alt),
            np.interp(high, self.sun_seconds, self.sun_alt),
        )
        first = np.searchsorted(self.sun_seconds, low, "right")
        last = np.searchsorted(self.sun_seconds, high, "left")
        inside = np.flatnonzero(first < last)
        if len(inside):
            # reduceat gives the minimum of [first, last) for each pair.
            values = np.append(self.sun_alt, np.inf)
            pairs = np.ravel(np.column_stack((first[inside], last[inside])))
            lowest[inside] = np.minimum(
                lowest[inside], np.minimum.reduceat(values, pairs)[::2]
            )
        return lowest

    def sun_at(self, seconds: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The Sun position (n, 3) and its altitude (n,) at ``seconds``."""
        sun_km = np.stack(
            [np.interp(seconds, self.sun_seconds, self.sun_km[:, i]) for i in range(3)],
            -1,
        )
        return sun_km, np.interp(seconds, self.sun_seconds, self.sun_alt)


class _Track:
    """SGP4 positions of some satellites on a uniform time grid, with cubic
    Hermite interpolation between the grid points."""

    def __init__(self, frame: _PassFrame, models: list[Satrec], count: int):
        self.frame = frame
        self.step = frame.span / (count - 1)
        self.seconds = np.arange(count) * self.step
        self.seconds[-1] = frame.span
        errors, teme_km, velocity = SatrecArray(models).sgp4(
            *frame.sgp4_dates(self.seconds)
        )
        self.ok = ~np.any(errors != 0, axis=1)
        self.teme_km = teme_km[self.ok]
        self.velocity = velocity[self.ok]

    def grid_altitude(self) -> np.ndarray:
        """(n, m) altitudes at the grid points."""
        return self.frame.altitude(self.frame.earth_fixed(self.teme_km, self.seconds))

    def earth_fixed_at(self, rows: np.ndarray, seconds: np.ndarray) -> np.ndarray:
        """Earth-fixed positions (k, 3) of satellites ``rows`` at ``seconds``."""
        last = len(self.seconds) - 2
        k = np.clip((seconds // self.step).astype(int), 0, last)
        h = self.seconds[k + 1] - self.seconds[k]
        s = ((seconds - self.seconds[k]) / h)[:, np.newaxis]
        s2, s3 = s * s, s * s * s
        h = h[:, np.newaxis]
        teme_km = (
            (2 * s3 - 3 * s2 + 1) * self.teme_km[rows, k]
            + (s3 - 2 * s2 + s) * h * self.velocity[rows, k]
            + (3 * s2 - 2 * s3) * self.teme_km[rows, k + 1]
            + (s3 - s2) * h * self.velocity[rows, k + 1]
        )
        return self.frame.earth_fixed(teme_km, seconds)

    def altitude_at(self, rows: np.ndarray, seconds: np.ndarray) -> np.ndarray:
        return self.frame.altitude(self.earth_fixed_at(rows, seconds))


def _iterations(width: float, factor: float) -> int:
    """Steps until a bracket of ``width`` seconds is below the tolerance."""
    if width <= PASS_TIME_TOLERANCE_SECONDS:
        return 0
    return int(
        math.ceil(math.log(width / PASS_TIME_TOLERANCE_SECONDS) / math.log(factor))
    )


def _maximize(track: _Track, rows, low, high) -> tuple[np.ndarray, np.ndarray]:
    """Golden section search for the highest altitude in [low, high]."""
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = low.copy(), high.copy()
    c = b - golden * (b - a)
    d = a + golden * (b - a)
    fc, fd = track.altitude_at(rows, c), track.altitude_at(rows, d)
    for _ in range(_iterations(float(np.max(b - a)), 1.0 / golden)):
        left = fc > fd
        b = np.where(left, d, b)
        a = np.where(left, a, c)
        new_c = np.where(left, b - golden * (b - a), d)
        new_d = np.where(left, c, a + golden * (b - a))
        value = track.altitude_at(rows, np.where(left, new_c, new_d))
        fc, fd = np.where(left, value, fd), np.where(left, fc, value)
        c, d = new_c, new_d
    best = (a + b) / 2.0
    return best, track.altitude_at(rows, best)


def _crossing(track: _Track, rows, low, high, min_alt: float, rising: bool):
    """Bisection for the time the altitude crosses ``min_alt``.

    The satellite is below ``min_alt`` at ``low`` when ``rising``, and at
    ``high`` when not.
    """
    for _ in range(_iterations(float(np.max(high - low, initial=0.0)), 2.0)):
        middle = (low + high) / 2.0
        up = track.altitude_at(rows, middle) >= min_alt
        if rising:
            low, high = np.where(up, low, middle), np.where(up, middle, high)
        else:
            low, high = np.where(up, middle, low), np.where(up, high, middle)
    return (low + high) / 2.0


def _chunk_passes(
    sats: list[TrackedSatellite],
    frame: _PassFrame,
    count: int,
    min_alt: float,
    failed: list[str],
) -> list[list[SatPass]]:
    """The passes of a few satellites, on a grid of ``count`` points."""
    track = _Track(frame, [sat.satellite.model for sat in sats], count)
    failed.extend(sat.name for sat, ok in zip(sats, track.ok) if not ok)
    good = [sat for sat, ok in zip(sats, track.ok) if ok]
    result: list[list[SatPass]] = [[] for _sat in sats]
    if not good:
        return result
    grid = track.seconds
    alt = track.grid_altitude()

    # The grid points that are higher than their neighbours. The true
    # highest point is less than one step away. The ends of the window
    # count when the altitude falls away from them.
    peak = np.zeros(alt.shape, dtype=bool)
    peak[:, 1:-1] = (alt[:, 1:-1] > alt[:, :-2]) & (alt[:, 1:-1] >= alt[:, 2:])
    peak[:, 0] = alt[:, 0] >= alt[:, 1]
    peak[:, -1] = alt[:, -1] > alt[:, -2]
    peak &= alt > min_alt - PASS_PEAK_MARGIN_DEG
    rows, columns = np.nonzero(peak)
    if len(rows) == 0:
        return result
    low = grid[np.maximum(columns - 1, 0)]
    high = grid[np.minimum(columns + 1, len(grid) - 1)]
    top, top_alt = _maximize(track, rows, low, high)
    # The grid point itself can be higher, at the end of the window.
    grid_alt = alt[rows, columns]
    better = grid_alt > top_alt
    top = np.where(better, grid[columns], top)
    top_alt = np.where(better, grid_alt, top_alt)
    keep = top_alt >= min_alt
    rows, top, top_alt = rows[keep], top[keep], top_alt[keep]
    if len(rows) == 0:
        return result

    # The grid points before and after each peak where the satellite is
    # below min_alt. The rise and the set are between those and the next
    # grid points.
    below = alt < min_alt
    index = np.arange(len(grid))
    last_below = np.maximum.accumulate(np.where(below, index, -1), axis=1)
    next_below = np.minimum.accumulate(
        np.where(below, index, len(grid))[:, ::-1], axis=1
    )[:, ::-1]
    before = np.minimum((top // track.step).astype(int), len(grid) - 1)
    after = np.minimum(before + 1, len(grid) - 1)
    rise_point = last_below[rows, before]
    set_point = np.where(top >= frame.span, len(grid), next_below[rows, after])

    # Two peaks with the same rise are one pass: keep the higher one.
    order = np.lexsort((-top_alt, rise_point, rows))
    rows, top, top_alt = rows[order], top[order], top_alt[order]
    rise_point, set_point = rise_point[order], set_point[order]
    first = np.ones(len(rows), dtype=bool)
    first[1:] = (rows[1:] != rows[:-1]) | (rise_point[1:] != rise_point[:-1])
    rows, top, top_alt = rows[first], top[first], top_alt[first]
    rise_point, set_point = rise_point[first], set_point[first]

    rise = np.zeros(len(rows))
    inside = rise_point >= 0
    if inside.any():
        point = rise_point[inside]
        rise[inside] = _crossing(
            track,
            rows[inside],
            grid[point],
            np.minimum(grid[point + 1], top[inside]),
            min_alt,
            rising=True,
        )
    set_time = np.full(len(rows), frame.span)
    inside = set_point < len(grid)
    if inside.any():
        point = set_point[inside]
        set_time[inside] = _crossing(
            track,
            rows[inside],
            np.maximum(grid[point - 1], top[inside]),
            grid[point],
            min_alt,
            rising=False,
        )

    passes = _describe_passes(good, track, rows, rise, top, top_alt, set_time)
    by_sat: dict[int, list[SatPass]] = {}
    for row, item in zip(rows.tolist(), passes):
        by_sat.setdefault(row, []).append(item)
    good_index = np.flatnonzero(track.ok)
    for row, items in by_sat.items():
        items.sort(key=lambda item: item.rise)
        result[int(good_index[row])] = items
    return result


def _describe_passes(
    sats: list[TrackedSatellite],
    track: _Track,
    rows: np.ndarray,
    rise: np.ndarray,
    top: np.ndarray,
    top_alt: np.ndarray,
    set_time: np.ndarray,
) -> list[SatPass]:
    """Directions, visibility and magnitude of the passes.

    Samples are PASS_STEP_SECONDS apart, or more for a pass longer than
    PASS_MAX_SAMPLES steps. A pass with a bright sky from rise to set gets
    no samples, because it cannot be visible.
    """
    frame = track.frame
    count = len(rows)
    ends = np.concatenate((rise, top, set_time))
    az = frame.horizon(track.earth_fixed_at(np.tile(rows, 3), ends))[1]
    rise_az, top_az, set_az = az[:count], az[count : 2 * count], az[2 * count :]
    visible_start = np.full(count, np.nan)
    visible_end = np.full(count, np.nan)
    min_mag = np.full(count, np.nan)

    dark = np.flatnonzero(frame.min_sun_alt(rise, set_time) < DARK_SUN_ALT_DEG)
    duration = np.maximum(set_time - rise, 1.0)
    counts = np.clip(
        (duration / PASS_STEP_SECONDS).astype(int) + 1, 2, PASS_MAX_SAMPLES
    )
    std_mag = np.array([sat.std_mag for sat in sats])

    # Batches of passes keep the number of samples at once small.
    total = np.cumsum(counts[dark])
    first = 0
    while first < len(dark):
        done = total[first - 1] if first else 0
        last = max(
            first + 1, int(np.searchsorted(total, done + PASS_CHUNK_SAMPLES, "right"))
        )
        batch = dark[first:last]
        first = last
        batch_counts = counts[batch]
        offsets = np.concatenate(([0], np.cumsum(batch_counts)[:-1]))
        owner = np.repeat(np.arange(len(batch)), batch_counts)
        step = (set_time[batch] - rise[batch]) / (batch_counts - 1)
        sample = np.arange(len(owner))
        seconds = rise[batch][owner] + (sample - offsets[owner]) * step[owner]
        sat_rows = rows[batch][owner]
        sat_km = track.earth_fixed_at(sat_rows, seconds)
        alt, _az, range_km = frame.horizon(sat_km)
        sun_km, sun_alt = frame.sun_at(seconds)
        sunlit = in_sunlight(sat_km.T, sun_km.T)
        phase = phase_angle_deg(sat_km.T, sun_km.T, frame.observer_km[:, np.newaxis])
        mags = _magnitudes(std_mag[sat_rows], range_km, phase)
        visible = sunlit & (sun_alt < DARK_SUN_ALT_DEG) & (alt > 0)

        start_index = np.minimum.reduceat(
            np.where(visible, sample, len(owner)), offsets
        )
        end_index = np.maximum.reduceat(np.where(visible, sample, -1), offsets)
        seen = end_index >= 0
        seen_batch = batch[seen]
        visible_start[seen_batch] = seconds[start_index[seen]]
        visible_end[seen_batch] = seconds[end_index[seen]]
        min_mag[seen_batch] = np.minimum.reduceat(
            np.where(visible, mags, np.inf), offsets
        )[seen]

    start = frame.start
    passes = []
    for values in zip(
        rise.tolist(),
        top.tolist(),
        set_time.tolist(),
        rise_az.tolist(),
        top_alt.tolist(),
        top_az.tolist(),
        set_az.tolist(),
        visible_start.tolist(),
        visible_end.tolist(),
        min_mag.tolist(),
    ):
        item = SatPass(
            rise=start + timedelta(seconds=values[0]),
            culmination=start + timedelta(seconds=values[1]),
            set=start + timedelta(seconds=values[2]),
            rise_az=values[3],
            max_alt=values[4],
            max_alt_az=values[5],
            set_az=values[6],
        )
        if not math.isnan(values[7]):
            item.visible_start = start + timedelta(seconds=values[7])
            item.visible_end = start + timedelta(seconds=values[8])
            item.min_mag = values[9]
        passes.append(item)
    return passes


AZ_NAMES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def compass(az: float) -> str:
    return AZ_NAMES[int(((az % 360.0) + 22.5) // 45.0) % 8]
