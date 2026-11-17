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
import fcntl
import io
import json
import logging
import math
import os
import re
import tempfile
import threading
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

import numpy as np
import requests
from sgp4 import exporter, omm
from sgp4.api import Satrec, SatrecArray
from sgp4.conveniences import sat_epoch_datetime
from sgp4.io import compute_checksum
from skyfield.api import EarthSatellite
from skyfield.framelib import itrs
from skyfield.sgp4lib import TEME, theta_GMST1982

from PiFinder.calc_utils import sf_utils
from PiFinder.composite_object import CompositeObject, MagnitudeObject, SizeObject
from PiFinder.download_utils import (
    ERROR_DATA,
    ERROR_HTTP,
    ERROR_NETWORK,
    ERROR_TIMEOUT,
    DownloadResult,
    download_atomic,
)
from PiFinder.satellite_groups import (  # noqa: F401 (re-exported names)
    AVAILABLE_GROUPS,
    CELESTRAK_GROUPS,
    DEFAULT_GROUPS,
    GROUPS_BY_NAME,
    CelestrakGroup,
)
from PiFinder.utils import astro_data_dir, satellite_data_dir


logger = logging.getLogger("Satellites")

CATALOG_CODE = "SA"
OBJ_TYPE = "Sat"
# The object id of a satellite is this base minus its NORAD number. It is the
# same in each process and after each build of the catalog, so the recent list
# holds one entry for each satellite. It is far below the virtual ids that
# VirtualIDManager mints, so the two never meet.
OBJECT_ID_BASE = -(1 << 40)

CELESTRAK_GROUP_URL = (
    "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
)
CELESTRAK_CATNR_URL = (
    "https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=tle"
)


USER_FILE_NAME = "user.tle"
CORRECTED_FILE_NAME = "corrected.tle"
# The element sets that the user owns: the pasted sets ("user") and the
# corrected sets of a mount follow ("corrected"). Each kind has its file, the
# Selection field of its disabled sets, and the source of its sets.
OWN_KINDS = {
    "user": (USER_FILE_NAME, "disabled_user", "user"),
    "corrected": (CORRECTED_FILE_NAME, "disabled_corrected", "corrected"),
}
# The text between the name and the time in the name of a corrected set.
CORRECTED_MARK = " corr "
USER_MAG_FILE_NAME = "user_mags.json"
SELECTION_FILE_NAME = "selection.json"
DOWNLOAD_STATUS_FILE_NAME = "download_status.json"
STD_MAG_FILE = astro_data_dir / "satellite_std_mags.csv"
# The CelesTrak "visual" group holds the brightest objects. A member without a
# magnitude in the table gets this value.
DEFAULT_STD_MAG = 4.0
# Element sets older than this give positions that are wrong by many degrees.
MAX_ELEMENT_AGE_DAYS = 30.0
# A geostationary orbit: one turn per sidereal day, almost circular. Such a
# satellite stays at one place in the sky, so it has no passes.
GEO_REVS_PER_DAY = 1.0027
GEO_REVS_TOLERANCE = 0.01
GEO_MAX_ECCENTRICITY = 0.01
# CelesTrak updates the groups a few times a day. It blocks (HTTP 403) a
# client that asks for the same data more often than every two hours.
DOWNLOAD_INTERVAL_HOURS = 12.0
# A download that the user asks for is refused when the last request that
# reached CelesTrak for that group is younger.
MIN_FORCED_DOWNLOAD_SECONDS = 2 * 3600.0
# The waits before the automatic retries of a group whose download failed.
# After the last wait, a failed group waits DOWNLOAD_INTERVAL_HOURS. When
# CelesTrak answered (an HTTP error), each wait is at least
# MIN_FORCED_DOWNLOAD_SECONDS. A network fault uses the short waits.
FAILED_RETRY_SECONDS = (5 * 60.0, 15 * 60.0, 60 * 60.0)
# A "downloading" state older than this is from a process that stopped.
DOWNLOAD_STALE_SECONDS = 15 * 60.0
# The pass predictions of the catalog and of the web page: the time window,
# which starts PASS_START_BEFORE_SECONDS before now, and the minimum altitude.
PASS_HOURS = 24.0
PASS_START_BEFORE_SECONDS = 15 * 60.0
MIN_PASS_ALT_DEG = 10.0
# A pass prediction is good for this long, and for a location change up to
# PASS_MOVE_DEG in latitude and in longitude.
PASS_GOOD_SECONDS = 30 * 60.0
PASS_MOVE_DEG = 0.5
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


# The launch year, the launch number of that year and the piece code.
_COSPAR_FIELD = re.compile(r"^(\d{2})(\d{3})([A-Z]{1,3})$")


def cospar_from_tle_field(field: str) -> str:
    """The international designator of a TLE field: "98067A" gives
    "1998-067A". Years 57-99 are 19xx and years 00-56 are 20xx. A field
    that is empty or has another form gives ""."""
    match = _COSPAR_FIELD.match(field.strip())
    if match is None:
        return ""
    year, number, piece = match.groups()
    century = "19" if int(year) >= 57 else "20"
    return f"{century}{year}-{number}{piece}"


@dataclass(frozen=True)
class SatElements:
    """One element set, normalized to TLE lines.

    ``parsed`` is the SGP4 record of the lines when the parser has it, so
    each set is parsed once. Without it, ``satrec`` parses the lines.
    """

    name: str
    norad_id: int
    line1: str
    line2: str
    source: str = "user"
    parsed: Optional[Satrec] = field(default=None, compare=False, repr=False)

    @cached_property
    def satrec(self) -> Satrec:
        if self.parsed is not None:
            return self.parsed
        return Satrec.twoline2rv(self.line1, self.line2)

    @cached_property
    def epoch(self) -> datetime:
        return sat_epoch_datetime(self.satrec)

    def age_days(self, now: datetime) -> float:
        return (now - self.epoch).total_seconds() / 86400.0

    def to_tle(self) -> str:
        return f"{self.name}\n{self.line1}\n{self.line2}\n"

    @cached_property
    def cospar_id(self) -> str:
        """The international designator, for example "1998-067A".

        TLE line 1 holds it in columns 10-17 as "98067A". Years 57-99 are
        19xx and years 00-56 are 20xx. An empty or bad field gives "".
        """
        return cospar_from_tle_field(self.line1[9:17])

    @property
    def revs_per_day(self) -> float:
        return float(self.line2[52:63])

    @property
    def eccentricity(self) -> float:
        return float("0." + self.line2[26:33].strip())

    @cached_property
    def geostationary(self) -> bool:
        """True for a satellite that stays at one place in the sky."""
        return (
            abs(self.revs_per_day - GEO_REVS_PER_DAY) < GEO_REVS_TOLERANCE
            and self.eccentricity < GEO_MAX_ECCENTRICITY
        )

    def to_earth_satellite(self) -> EarthSatellite:
        satellite = EarthSatellite.from_satrec(self.satrec, sf_utils.ts)
        satellite.name = self.name
        return satellite


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
        """The times in ISO format, the angles and the magnitude to 0.1."""
        result: dict = {"visible": self.visible}
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, float):
                value = round(value, 1)
            result[item.name] = value
        return result


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _check_tle_lines(line1: str, line2: str) -> Satrec:
    """The SGP4 record of two valid TLE lines.

    The record reads the catalog number, also in the Alpha-5 form
    (A0001 = 100001).
    """
    if len(line1) < 69 or len(line2) < 69:
        raise ElementParseError("a TLE line is shorter than 69 characters")
    for line in (line1, line2):
        if line[68].isdigit() and int(line[68]) != compute_checksum(line):
            raise ElementParseError(f"bad checksum in line {line[:1]}")
    if line1[2:7] != line2[2:7]:
        raise ElementParseError("line 1 and line 2 have different catalog numbers")
    try:
        return Satrec.twoline2rv(line1, line2)
    except (ValueError, IndexError) as exc:
        raise ElementParseError(f"SGP4 rejects the lines: {exc}") from exc


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
                satrec = _check_tle_lines(line1, line2)
                name = pending_name or f"NORAD {satrec.satnum}"
                results.append(
                    SatElements(name, satrec.satnum, line1, line2, source, satrec)
                )
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


# The values of the OMM fields that a record can leave out.
_OMM_DEFAULTS = {
    "CLASSIFICATION_TYPE": "U",
    "ELEMENT_SET_NO": "999",
    "REV_AT_EPOCH": "0",
    "EPHEMERIS_TYPE": "0",
    "OBJECT_ID": "",
    "MEAN_MOTION_DOT": "0",
    "MEAN_MOTION_DDOT": "0",
    "BSTAR": "0",
}


def _omm_to_elements(record: dict, source: str) -> SatElements:
    values = {
        str(key).upper(): value if isinstance(value, str) else str(value)
        for key, value in record.items()
        if value is not None
    }
    values = {**_OMM_DEFAULTS, **values}
    try:
        satrec = Satrec()
        omm.initialize(satrec, values)
        line1, line2 = exporter.export_tle(satrec)
    except (KeyError, ValueError) as exc:
        raise ElementParseError(f"OMM record is incomplete: {exc}") from exc
    name = values.get("OBJECT_NAME", "").strip() or f"NORAD {satrec.satnum}"
    parsed = _check_tle_lines(line1, line2)
    return SatElements(name[:40], parsed.satnum, line1, line2, source, parsed)


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
    first_line = stripped.split("\n", 1)[0].upper()
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
        elif first_line.startswith("OBJECT_NAME,") or (
            "NORAD_CAT_ID" in first_line and "," in first_line
        ):
            reader = csv.DictReader(io.StringIO(stripped))
            results, errors = _parse_omm_records(reader, source)
        else:
            results, errors = _parse_tle_text(stripped, source)
    except ElementParseError:
        raise
    except (json.JSONDecodeError, SyntaxError) as exc:
        raise ElementParseError(f"the text is not valid JSON or XML: {exc}") from exc
    except Exception as exc:  # the sgp4 XML reader raises many types
        raise ElementParseError(f"cannot read the text: {exc}") from exc
    if not results and not errors:
        raise ElementParseError("no element set found in the text")
    return results, errors


# ---------------------------------------------------------------------------
# Storage and downloads
# ---------------------------------------------------------------------------


def group_file(group: str, directory: Path = satellite_data_dir) -> Path:
    return directory / f"{group}.tle"


def own_file(kind: str, directory: Path = satellite_data_dir) -> Path:
    """The file of the user element sets of ``kind`` (see OWN_KINDS)."""
    return directory / OWN_KINDS[kind][0]


def user_file(directory: Path = satellite_data_dir) -> Path:
    return own_file("user", directory)


def corrected_file(directory: Path = satellite_data_dir) -> Path:
    return own_file("corrected", directory)


def element_files(directory: Path = satellite_data_dir) -> list[Path]:
    """The files that decide the satellites and their passes: the selected
    groups, the user sets, the magnitudes and the selection. A file in the
    list can be absent."""
    return [
        *(group_file(group, directory) for group in selected_groups(directory)),
        user_file(directory),
        corrected_file(directory),
        user_mag_file(directory),
        selection_file(directory),
    ]


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
    """CelesTrak sends no Last-Modified, so the file age decides.

    A group whose last download failed waits until its retry time.
    """
    status = load_download_status(directory).get(group)
    if (
        status is not None
        and status.result == RESULT_FAILED
        and status.next_retry is not None
        and now.timestamp() < status.next_retry
    ):
        return False, "the last download failed, retry later"
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
    "too_soon" (CelesTrak answered for each group a short time ago) or
    "failed". ``refused`` holds each group that CelesTrak answered a short
    time ago (see ``forced_download_wait``), with the seconds until a
    forced download is permitted.
    """

    status: str
    failed: tuple[str, ...] = ()
    wait_seconds: float = 0.0
    downloaded: tuple[str, ...] = ()
    refused: tuple[tuple[str, float], ...] = ()
    # The reason of each failed group, see ``download_error_text``.
    errors: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return self.status in ("downloaded", "current", "no_groups")

    def error_of(self, group: str) -> str:
        return dict(self.errors).get(group, "")


_download_lock = threading.Lock()


def forced_download_wait(
    now: datetime,
    directory: Path = satellite_data_dir,
    groups: Optional[Iterable[str]] = None,
) -> dict[str, float]:
    """Seconds until a forced download of each group is permitted.

    The later of the file time and the last request that reached CelesTrak
    must be MIN_FORCED_DOWNLOAD_SECONDS old. Without ``groups`` the selected groups are used.
    """
    if groups is None:
        groups = selected_groups(directory)
    status = load_download_status(directory)
    waits: dict[str, float] = {}
    for group in groups:
        path = group_file(group, directory)
        times = [path.stat().st_mtime] if path.exists() else []
        entry = status.get(group)
        if entry is not None and entry.last_request is not None:
            times.append(entry.last_request)
        age = now.timestamp() - max(times) if times else None
        # A time in the future means the clock changed: permit the download.
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
    that ``forced_download_wait`` refuses.
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
        errors = []
        for group in wanted:
            record_download_start(group, now, directory)
            try:
                result = download_group(group, directory, progress_callback)
            except Exception as exc:  # a fault in one group must not stop the rest
                logger.exception("Download of satellite group %s failed", group)
                result = DownloadResult(False, None, None, str(exc))
            if result.success:
                downloaded.append(group)
            else:
                failed.append(group)
                errors.append((group, download_error_text(result)))
            record_download_end(group, now, result, directory)
        return GroupRefresh(
            "failed" if failed else "downloaded",
            tuple(failed),
            wait,
            tuple(downloaded),
            tuple(refused),
            tuple(errors),
        )
    finally:
        _download_lock.release()


# ---------------------------------------------------------------------------
# Download status
# ---------------------------------------------------------------------------

RESULT_OK = "ok"
RESULT_FAILED = "failed"
RESULT_DOWNLOADING = "downloading"

# A lock for the threads of this process. The lock file is for the other
# process: the device and the web server both write the status file.
_status_lock = threading.Lock()


@dataclass(frozen=True)
class GroupStatus:
    """The download state of one group, as stored in the status file.

    The times are seconds since 1970 (UTC), from the system clock, as the
    file times. ``failures`` counts the failed downloads since the last
    download that worked.
    """

    result: str
    last_attempt: Optional[float] = None
    last_success: Optional[float] = None
    error: str = ""
    sets: int = 0
    failures: int = 0
    next_retry: Optional[float] = None
    # The last request that reached CelesTrak: a download, an HTTP error or
    # bad data. A network fault does not count.
    last_request: Optional[float] = None

    def current_result(self, now: datetime) -> str:
        """The result. A download that started long ago counts as failed."""
        if (
            self.result == RESULT_DOWNLOADING
            and self.last_attempt is not None
            and now.timestamp() - self.last_attempt > DOWNLOAD_STALE_SECONDS
        ):
            return RESULT_FAILED
        return self.result

    @classmethod
    def from_dict(cls, data: dict) -> "GroupStatus":
        def number(key: str) -> Optional[float]:
            value = data.get(key)
            return float(value) if isinstance(value, (int, float)) else None

        return cls(
            str(data.get("result", "")),
            number("last_attempt"),
            number("last_success"),
            str(data.get("error") or ""),
            int(data.get("sets") or 0),
            int(data.get("failures") or 0),
            number("next_retry"),
            number("last_request"),
        )


def download_status_file(directory: Path = satellite_data_dir) -> Path:
    return directory / DOWNLOAD_STATUS_FILE_NAME


def load_download_status(
    directory: Path = satellite_data_dir,
) -> dict[str, GroupStatus]:
    """The stored download state of each group. A bad file gives {}."""
    try:
        data = json.loads(download_status_file(directory).read_text())
        return {
            str(group): GroupStatus.from_dict(entry)
            for group, entry in data.get("groups", {}).items()
            if isinstance(entry, dict)
        }
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def retry_wait_seconds(failures: int, server_answered: bool = False) -> float:
    """The wait before the next automatic download after ``failures``
    failed downloads in a row. When CelesTrak answered the last request,
    the wait is at least MIN_FORCED_DOWNLOAD_SECONDS."""
    if failures <= 0 or failures > len(FAILED_RETRY_SECONDS):
        return DOWNLOAD_INTERVAL_HOURS * 3600.0
    wait = FAILED_RETRY_SECONDS[failures - 1]
    if server_answered:
        wait = max(wait, MIN_FORCED_DOWNLOAD_SECONDS)
    return wait


@contextmanager
def _file_lock(path: Path, thread_lock: threading.Lock) -> Iterator[None]:
    """Keep the threads of this process apart with ``thread_lock``, and the
    processes (the device and the web server) with the lock file ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with thread_lock, open(path, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _update_status(directory: Path, group: str, change: Callable) -> None:
    """Replace the entry of ``group`` with ``change(old entry or None)``.

    A write that fails is logged: the download result stays good.
    """
    path = download_status_file(directory)
    try:
        with _file_lock(path.with_suffix(".lock"), _status_lock):
            entries = load_download_status(directory)
            entries[group] = change(entries.get(group))
            _write_json(
                path,
                {
                    "version": 1,
                    "groups": {
                        name: asdict(entry) for name, entry in sorted(entries.items())
                    },
                },
            )
    except OSError:
        logger.exception("Could not write the download status of %s", group)


def record_download_start(
    group: str, now: datetime, directory: Path = satellite_data_dir
) -> None:
    def change(old: Optional[GroupStatus]) -> GroupStatus:
        return replace(
            old or GroupStatus(RESULT_DOWNLOADING),
            result=RESULT_DOWNLOADING,
            last_attempt=now.timestamp(),
        )

    _update_status(directory, group, change)


def record_download_end(
    group: str,
    now: datetime,
    result: DownloadResult,
    directory: Path = satellite_data_dir,
) -> None:
    attempt = now.timestamp()

    def change(old: Optional[GroupStatus]) -> GroupStatus:
        old = old or GroupStatus(RESULT_FAILED)
        if result.success:
            path = group_file(group, directory)
            return GroupStatus(
                RESULT_OK,
                attempt,
                attempt,
                "",
                count_sets(path) if path.exists() else 0,
                0,
                attempt + retry_wait_seconds(0),
                attempt,
            )
        failures = old.failures + 1
        answered = result.kind in (ERROR_HTTP, ERROR_DATA)
        return replace(
            old,
            result=RESULT_FAILED,
            last_attempt=attempt,
            error=download_error_text(result),
            failures=failures,
            next_retry=attempt + retry_wait_seconds(failures, answered),
            last_request=attempt if answered else old.last_request,
        )

    _update_status(directory, group, change)


def catalog_empty_reason(directory: Path = satellite_data_dir) -> dict:
    """Why the element files give no objects.

    See ``SatelliteCatalog.get_status`` for the reasons.

    The reason "downloading" means that a process downloads a group now.
    """
    now = datetime.now(timezone.utc)
    groups = selected_groups(directory)
    has_own = any(load_own_elements(kind, directory) for kind in OWN_KINDS)
    if not groups and not has_own:
        return {"reason": "no_groups"}
    status = load_download_status(directory)
    results = {
        group: status[group].current_result(now) for group in groups if group in status
    }
    if any(result == RESULT_DOWNLOADING for result in results.values()):
        return {"reason": "downloading"}
    failed = [group for group in groups if results.get(group) == RESULT_FAILED]
    if failed:
        return {"reason": "failed", "groups": failed}
    if any(not group_file(group, directory).exists() for group in groups):
        return {"reason": "no_data"}
    return {"reason": "too_old"}


def count_sets(path: Path) -> int:
    """The number of element sets in a TLE file, without a parse of each set.

    A large group holds thousands of sets. A parse of each on each page load
    takes too long on a Pi.
    """
    with path.open(errors="replace") as handle:
        return sum(1 for line in handle if line.startswith("1 "))


# The reasons of a failed download: a code and the text of the web page. The
# status file stores the text. An HTTP error without its own code has the
# text "Server error N" or "HTTP error N", with code "http".
DOWNLOAD_ERRORS = {
    "no_data": "CelesTrak has no data",
    "refused": "Refused by CelesTrak (403)",
    "network": "No network",
    "timeout": "No answer from server",
    "bad_data": "No valid data",
    "failed": "Download failed",
}
_ERROR_KIND_CODES = {
    ERROR_NETWORK: "network",
    ERROR_TIMEOUT: "timeout",
    ERROR_DATA: "bad_data",
}
_HTTP_ERROR_PREFIXES = ("Server error ", "HTTP error ")


def download_error_text(result: DownloadResult) -> str:
    """A short reason for a failed download, for the device and the web page."""
    if result.kind == ERROR_HTTP:
        code = result.status_code
        if code == 404 and "No GP data found" in result.body:
            return DOWNLOAD_ERRORS["no_data"]
        if code is not None and code >= 500:
            return f"Server error {code}"
        if code == 403:
            return DOWNLOAD_ERRORS["refused"]
        if code is not None:
            return f"HTTP error {code}"
        return "HTTP error"
    return DOWNLOAD_ERRORS[_ERROR_KIND_CODES.get(result.kind or "", "failed")]


def download_error_code(text: str) -> str:
    """The code of a reason that ``download_error_text`` made."""
    for code, known in DOWNLOAD_ERRORS.items():
        if text == known:
            return code
    if text.startswith(_HTTP_ERROR_PREFIXES):
        return "http"
    return "failed"


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
USER_DATA_LOCK_NAME = "user_data.lock"


def _user_data_lock(directory: Path) -> AbstractContextManager[None]:
    """Keep a read and a write of the user files apart."""
    return _file_lock(directory / USER_DATA_LOCK_NAME, _user_file_lock)


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


def load_own_elements(
    kind: str, directory: Path = satellite_data_dir
) -> list[SatElements]:
    """The user element sets of ``kind`` (see OWN_KINDS)."""
    return read_tle_file(own_file(kind, directory), OWN_KINDS[kind][2])


def load_user_elements(directory: Path = satellite_data_dir) -> list[SatElements]:
    return load_own_elements("user", directory)


def load_corrected_elements(directory: Path = satellite_data_dir) -> list[SatElements]:
    return load_own_elements("corrected", directory)


def _save_own_elements(
    kind: str, new: Iterable[SatElements], directory: Path
) -> list[SatElements]:
    """Add or replace sets of ``kind``, keyed by NORAD id. The caller holds
    the user data lock."""
    by_id = {e.norad_id: e for e in load_own_elements(kind, directory)}
    for element in new:
        by_id[element.norad_id] = replace(element, source=OWN_KINDS[kind][2])
    elements = list(by_id.values())
    _write_text(own_file(kind, directory), "".join(e.to_tle() for e in elements))
    return elements


def save_user_elements(
    new: Iterable[SatElements], directory: Path = satellite_data_dir
) -> list[SatElements]:
    """Add or replace user element sets, keyed by NORAD id."""
    with _user_data_lock(directory):
        return _save_own_elements("user", new, directory)


def delete_element(
    kind: str, norad_id: int, directory: Path = satellite_data_dir
) -> bool:
    """Remove a user set of ``kind`` and its selection entry. A pasted set
    ("user") also loses its magnitude."""
    with _user_data_lock(directory):
        current = load_own_elements(kind, directory)
        kept = [e for e in current if e.norad_id != norad_id]
        if len(kept) == len(current):
            return False
        _write_text(own_file(kind, directory), "".join(e.to_tle() for e in kept))
        if kind == "user":
            mags = load_user_mags(directory)
            if mags.pop(norad_id, None) is not None:
                _write_mags(mags, directory)
        _change_disabled(kind, norad_id, False, directory)
        return True


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
    corrected = replace(
        element, name=corrected_name(element.name, when), source="corrected"
    )
    with _user_data_lock(directory):
        _save_own_elements("corrected", [corrected], directory)
    return corrected


def _write_text(path: Path, text: str) -> None:
    """Replace the file in one step. The temporary file has a unique name,
    so two writers never share it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(handle, "w") as temporary:
            temporary.write(text)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def _write_json(path: Path, data: dict) -> None:
    _write_text(path, json.dumps(data))


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

    def enabled(self, kind: str, norad_id: int) -> bool:
        """True when the user set ``norad_id`` of ``kind`` is not disabled."""
        disabled: frozenset[int] = getattr(self, OWN_KINDS[kind][1])
        return norad_id not in disabled


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
    with _user_data_lock(directory):
        selection = load_selection(directory)
        groups = selection.groups - {group}
        if enabled:
            groups = groups | {group}
        _write_selection(replace(selection, groups=groups), directory)


def _change_disabled(kind: str, norad_id: int, disabled: bool, directory: Path) -> None:
    """Add ``norad_id`` to the disabled sets of ``kind``, or remove it. The
    caller holds the user data lock."""
    selection = load_selection(directory)
    name = OWN_KINDS[kind][1]
    current: frozenset[int] = getattr(selection, name)
    changed = current | {norad_id} if disabled else current - {norad_id}
    if changed != current:
        fields_to_change: dict[str, Any] = {name: changed}
        _write_selection(replace(selection, **fields_to_change), directory)


def set_enabled(
    kind: str, norad_id: int, enabled: bool, directory: Path = satellite_data_dir
) -> None:
    """Enable or disable the user set ``norad_id`` of ``kind``."""
    if kind not in OWN_KINDS:
        raise ValueError(f"not a kind of user set: {kind}")
    with _user_data_lock(directory):
        _change_disabled(kind, norad_id, not enabled, directory)


@dataclass(frozen=True)
class _StoredSets:
    """The element sets of the files, before the merge."""

    groups: dict[str, list[SatElements]]
    own: dict[str, list[SatElements]]

    @classmethod
    def read(cls, directory: Path, groups: Iterable[str]) -> "_StoredSets":
        return cls(
            {
                group: read_tle_file(group_file(group, directory), "celestrak")
                for group in groups
            },
            {kind: load_own_elements(kind, directory) for kind in OWN_KINDS},
        )

    def merge(
        self, now: datetime, selection: Optional[Selection] = None
    ) -> list[SatElements]:
        """One set per NORAD id, without sets that are too old. With a
        ``selection``, the groups that are not selected and the disabled
        sets are left out."""
        by_id: dict[int, SatElements] = {}
        for group, elements in self.groups.items():
            if selection is not None and not selection.group_enabled(group):
                continue
            for element in elements:
                by_id.setdefault(element.norad_id, element)
        for kind, elements in self.own.items():
            for element in elements:
                if selection is not None and not selection.enabled(
                    kind, element.norad_id
                ):
                    continue
                existing = by_id.get(element.norad_id)
                if existing is None or _replaces(kind, element, existing):
                    by_id[element.norad_id] = element
        return [
            e for e in by_id.values() if abs(e.age_days(now)) <= MAX_ELEMENT_AGE_DAYS
        ]


def _replaces(kind: str, element: SatElements, existing: SatElements) -> bool:
    """A user set replaces a set of the same object only if it is newer, so
    a pasted TLE does not stay in use after CelesTrak has a fresh one. A
    corrected set keeps the epoch of the set it corrects. It replaces a set
    of the same epoch or older, so a newer download replaces the correction."""
    if kind == "corrected":
        return element.epoch >= existing.epoch
    return element.epoch > existing.epoch


def load_all_elements(
    now: datetime,
    directory: Path = satellite_data_dir,
    include_disabled: bool = False,
) -> list[SatElements]:
    """All element sets, one per NORAD id, without sets that are too old.

    Groups that are not selected and sets that the user disabled are left
    out, unless ``include_disabled`` is set. Then each group file on disk
    is read.
    """
    if include_disabled:
        return _StoredSets.read(directory, CELESTRAK_GROUPS).merge(now)
    selection = load_selection(directory)
    groups = [group for group in CELESTRAK_GROUPS if selection.group_enabled(group)]
    return _StoredSets.read(directory, groups).merge(now, selection)


def find_elements(
    norad_id: int, now: datetime, directory: Path = satellite_data_dir
) -> tuple[Optional[SatElements], bool]:
    """The set of one satellite, as ``load_all_elements`` with
    ``include_disabled`` gives it, and True when the catalog uses the
    satellite. Each file is read once."""
    stored = _StoredSets.read(directory, CELESTRAK_GROUPS)
    every = {e.norad_id: e for e in stored.merge(now)}
    in_use = stored.merge(now, load_selection(directory))
    return every.get(norad_id), any(e.norad_id == norad_id for e in in_use)


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
    with _user_data_lock(directory):
        mags = load_user_mags(directory)
        if std_mag is None:
            mags.pop(norad_id, None)
        else:
            mags[norad_id] = float(std_mag)
        _write_mags(mags, directory)


def _write_mags(mags: dict[int, float], directory: Path) -> None:
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


def _phase_functions(phase_deg) -> np.ndarray:
    """Diffuse sphere brightness relative to full phase (1.0 at 0 degrees)."""
    phi = np.radians(phase_deg)
    return ((np.pi - phi) * np.cos(phi) + np.sin(phi)) / np.pi


def phase_function(phase_angle_deg: float) -> float:
    """Diffuse sphere brightness relative to full phase (1.0 at 0 degrees)."""
    return float(_phase_functions(phase_angle_deg))


def apparent_magnitude(
    std_mag: float, range_km: float, phase_angle_deg: float
) -> float:
    """Magnitude from the standard magnitude at 1000 km and 90 degrees phase."""
    return float(_magnitudes(std_mag, range_km, phase_angle_deg))


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


def load_tracked(
    now: datetime, directory: Path = satellite_data_dir
) -> list[TrackedSatellite]:
    """The satellites of ``load_all_elements``, ready for positions. A set
    that Skyfield cannot use is left out."""
    user_mags = load_user_mags(directory)
    tracked = []
    for element in load_all_elements(now, directory):
        try:
            tracked.append(TrackedSatellite.from_elements(element, user_mags))
        except ValueError as exc:
            logger.warning("Skipping %s: %s", element.name, exc)
    return tracked


def make_object(
    norad_id: int, name: str, ra: float = 0.0, dec: float = 0.0
) -> CompositeObject:
    """The object of a satellite for the object lists and the recent list."""
    return CompositeObject.from_dict(
        {
            "id": -1,
            "object_id": OBJECT_ID_BASE - norad_id,
            "obj_type": OBJ_TYPE,
            "ra": ra,
            "dec": dec,
            "const": "",
            "size": SizeObject([]),
            "mag": MagnitudeObject([]),
            "mag_str": "-",
            "names": [name],
            "catalog_code": CATALOG_CODE,
            "sequence": norad_id,
            "description": "",
        }
    )


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


def look(sat: TrackedSatellite, topos, dt: datetime) -> SatLook:
    """Position, brightness and motion of a satellite at ``dt``.

    The position and the brightness come from ``look_many``. The RA/Dec
    rates come from a second position RATE_STEP_SECONDS later.
    """
    (now,) = look_many([sat], topos, dt)
    later = now.time + timedelta(seconds=RATE_STEP_SECONDS)
    ra, dec, _alt = sky_tracks([sat], topos, [later])
    ra_step = (float(ra[0, 0]) - now.ra + 540.0) % 360.0 - 180.0
    now.ra_rate = ra_step / RATE_STEP_SECONDS
    now.dec_rate = (float(dec[0, 0]) - now.dec) / RATE_STEP_SECONDS
    return now


def _magnitudes(std_mag, range_km, phase_deg) -> np.ndarray:
    """``apparent_magnitude`` for arrays."""
    relative = _phase_functions(phase_deg) / _phase_functions(90.0)
    return (
        std_mag
        + 5.0 * np.log10(np.asarray(range_km) / 1000.0)
        - 2.5 * np.log10(np.maximum(relative, 1e-4))
    )


def satrec_array(sats: list[TrackedSatellite]) -> SatrecArray:
    """The SGP4 models of ``sats`` for one vectorized call. Building it costs
    time for many satellites, so a caller that propagates the same
    satellites again keeps it."""
    return SatrecArray([sat.satellite.model for sat in sats])


def _geometry_many(
    sats: list[TrackedSatellite],
    topos,
    times: list[datetime],
    array: Optional[SatrecArray] = None,
):
    """Positions of n satellites at m times with one SGP4 call.

    Returns the Skyfield times, the geocentric positions in km (3, n, m),
    the positions relative to the observer in km (3, n, m), the altitude
    and the azimuth in degrees (n, m). A satellite that SGP4 cannot
    propagate gets NaN. ``array`` is ``satrec_array(sats)``, when the caller
    keeps one.
    """
    t = sf_utils.ts.from_datetimes(times)
    days = np.array([dt.timestamp() for dt in times]) / 86400.0
    whole = np.floor(days)
    if array is None:
        array = satrec_array(sats)
    _errors, teme_km, _velocity = array.sgp4(whole + UNIX_EPOCH_JD, days - whole)
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
    return sky_state_many(sats, topos, dt, sun=sun).looks()


@dataclass
class SkyState:
    """Positions and brightness of many satellites at one time, as arrays.

    Element i of each array belongs to ``norad_ids[i]``. Angles are in
    degrees, RA/Dec in J2000. ``mag`` is NaN for a satellite in Earth's
    shadow, and each value is NaN for a satellite that SGP4 cannot
    propagate. ``sun_alt`` is the altitude of the Sun for the observer.
    """

    time: datetime
    norad_ids: np.ndarray
    ra: np.ndarray
    dec: np.ndarray
    alt: np.ndarray
    az: np.ndarray
    range_km: np.ndarray
    mag: np.ndarray
    sun_alt: float

    @classmethod
    def empty(cls, dt: datetime) -> "SkyState":
        nothing = np.zeros(0)
        return cls(
            time=dt,
            norad_ids=np.zeros(0, dtype=np.int64),
            ra=nothing,
            dec=nothing,
            alt=nothing,
            az=nothing,
            range_km=nothing,
            mag=nothing,
            sun_alt=math.nan,
        )

    def looks(self) -> list[SatLook]:
        """One ``SatLook`` per satellite, in the order of ``norad_ids``."""
        sunlit = np.isfinite(self.mag)
        return [
            SatLook(
                time=self.time,
                ra=float(self.ra[i]),
                dec=float(self.dec[i]),
                alt=float(self.alt[i]),
                az=float(self.az[i]),
                range_km=float(self.range_km[i]),
                sunlit=bool(sunlit[i]),
                sun_alt=self.sun_alt,
                mag=float(self.mag[i]) if sunlit[i] else None,
            )
            for i in range(len(self.norad_ids))
        ]


def _radec_of(relative_km: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """RA/Dec in degrees of positions relative to the observer (3, ...)."""
    range_km = np.linalg.norm(relative_km, axis=0)
    ra = np.degrees(np.arctan2(relative_km[1], relative_km[0])) % 360.0
    dec = np.degrees(np.arcsin(relative_km[2] / range_km))
    return ra, dec


def sky_state_many(
    sats: list[TrackedSatellite],
    topos,
    dt: datetime,
    array: Optional[SatrecArray] = None,
    sun: Optional[SunContext] = None,
) -> SkyState:
    """Positions and magnitudes of many satellites at one time, with one
    SGP4 call. ``array`` is ``satrec_array(sats)``, when the caller keeps
    one. Give ``sun`` from ``sun_context`` when the caller has it."""
    dt = _as_utc(dt)
    if not sats:
        return SkyState.empty(dt)
    if sun is None:
        sun = sun_context(topos, dt)
    t, sat_km, relative_km, alt, az = _geometry_many(sats, topos, [dt], array)
    sat_km, relative_km = sat_km[:, :, 0], relative_km[:, :, 0]
    ra, dec = _radec_of(relative_km)
    sun_km = sun.sun_geocentric_km[:, np.newaxis]
    sunlit = in_sunlight(sat_km, sun_km)
    phase = phase_angle_deg(sat_km, sun_km, topos.at(t).position.km)
    range_km = np.linalg.norm(relative_km, axis=0)
    mags = _magnitudes(np.array([sat.std_mag for sat in sats]), range_km, phase)
    return SkyState(
        time=dt,
        norad_ids=np.array([sat.norad_id for sat in sats], dtype=np.int64),
        ra=ra,
        dec=dec,
        alt=alt[:, 0],
        az=az[:, 0],
        range_km=range_km,
        mag=np.where(sunlit, mags, np.nan),
        sun_alt=sun.sun_alt,
    )


def sky_tracks(
    sats: list[TrackedSatellite], topos, times: list[datetime]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """J2000 RA, Dec and altitude in degrees of n satellites at m times,
    each as an (n, m) array, with one SGP4 call."""
    if not sats:
        nothing = np.zeros((0, len(times)))
        return nothing, nothing, nothing
    _t, _sat_km, relative_km, alt, _az = _geometry_many(sats, topos, times)
    ra, dec = _radec_of(relative_km)
    return ra, dec, alt


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


def predict_passes(
    tracked: Iterable[TrackedSatellite], topos, now: datetime
) -> list[tuple[TrackedSatellite, list[SatPass]]]:
    """The passes of the catalog and of the web page: PASS_HOURS from
    PASS_START_BEFORE_SECONDS before ``now``. A geostationary satellite has
    no passes, so it is left out."""
    sats = [sat for sat in tracked if not sat.elements.geostationary]
    start = now - timedelta(seconds=PASS_START_BEFORE_SECONDS)
    found = find_passes_many(sats, topos, start, PASS_HOURS, MIN_PASS_ALT_DEG)
    return list(zip(sats, found))


def passes_stale(
    computed: datetime, lat: float, lon: float, now: datetime, location
) -> bool:
    """True when passes for ``computed`` at ``lat`` and ``lon`` are not good
    for ``now`` at ``location``: too old, or for another place."""
    moved = abs(lat - location.lat) > PASS_MOVE_DEG or (
        abs(lon - location.lon) > PASS_MOVE_DEG
    )
    return moved or abs((now - computed).total_seconds()) > PASS_GOOD_SECONDS


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
