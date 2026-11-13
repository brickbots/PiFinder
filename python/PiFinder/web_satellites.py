"""Data for the satellite web pages.

The web server runs in its own process. It reads the element files and
computes the passes itself. The pass table of the selected satellites takes
many seconds on a Pi, so a background thread computes it, and the table
stays in memory for some time (see ``PassTable``).
"""

from __future__ import annotations

import datetime
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import pytz

import PiFinder.satellites as satellites
from PiFinder.utils import Timer, satellite_data_dir


# The pass table on the web page lists passes this bright or brighter.
DEFAULT_MAX_MAG = 4.0
# The largest element file that the web form accepts.
MAX_UPLOAD_BYTES = 1_000_000
# The pass table: its time window, its minimum altitude and its row limit.
PASS_HOURS = 24.0
MIN_PASS_ALT_DEG = 10.0
PASS_TABLE_ROWS = 200
# A pass table is good for this long, and for a location change up to
# PASS_TABLE_MOVE_DEG in latitude and in longitude.
PASS_TABLE_SECONDS = 30 * 60
PASS_TABLE_MOVE_DEG = 0.5

logger = logging.getLogger("WebSatellites")


def _zone(name: Optional[str]):
    try:
        return pytz.timezone(name or "UTC")
    except pytz.exceptions.UnknownTimeZoneError:
        return pytz.utc


def _local(iso: Optional[str], zone) -> str:
    if not iso:
        return ""
    return datetime.datetime.fromisoformat(iso).astimezone(zone).strftime("%a %H:%M:%S")


def format_pass(row: dict, zone) -> dict:
    """A pass row of the cache with local times and compass directions."""
    result = dict(row)
    for key in ("rise", "culmination", "set", "visible_start", "visible_end"):
        result[f"{key}_local"] = _local(row.get(key), zone)
    result["rise_dir"] = satellites.compass(row["rise_az"])
    result["max_dir"] = satellites.compass(row["max_alt_az"])
    result["set_dir"] = satellites.compass(row["set_az"])
    return result


def _count_sets(path: Path) -> int:
    """The number of element sets in a TLE file, without a parse of each set.

    A large group holds thousands of sets. A parse of each on each page load
    takes too long on a Pi.
    """
    with path.open(errors="replace") as handle:
        return sum(1 for line in handle if line.startswith("1 "))


def group_status(now: datetime.datetime, directory: Path = satellite_data_dir) -> list:
    """One row for each CelesTrak group that the user can select."""
    selection = satellites.load_selection(directory)
    rows = []
    for group in satellites.AVAILABLE_GROUPS:
        path = satellites.group_file(group.name, directory)
        if path.exists():
            age_hours = (now.timestamp() - path.stat().st_mtime) / 3600.0
            count = _count_sets(path)
        else:
            age_hours, count = None, 0
        rows.append(
            {
                "group": group.name,
                "label": group.label,
                "large": group.large,
                "age_hours": age_hours,
                "count": count,
                "enabled": selection.group_enabled(group.name),
            }
        )
    return rows


def user_satellites(
    now: datetime.datetime, directory: Path = satellite_data_dir
) -> list:
    selection = satellites.load_selection(directory)
    rows = []
    for element in satellites.load_user_elements(directory):
        age = element.age_days(now)
        rows.append(
            {
                "norad_id": element.norad_id,
                "name": element.name,
                "epoch": element.epoch.strftime("%Y-%m-%d %H:%M"),
                "age_days": age,
                "too_old": abs(age) > satellites.MAX_ELEMENT_AGE_DAYS,
                "line1": element.line1,
                "line2": element.line2,
                "enabled": selection.user_enabled(element.norad_id),
            }
        )
    rows.sort(key=lambda row: str(row["name"]))
    return rows


def corrected_satellites(
    now: datetime.datetime, directory: Path = satellite_data_dir
) -> list:
    """The rows of the corrected sets. A row is in use when the catalog uses
    the set: it is enabled and no newer set of the satellite exists."""
    selection = satellites.load_selection(directory)
    in_use = {
        e.norad_id
        for e in satellites.load_all_elements(now, directory)
        if e.source == "corrected"
    }
    rows = []
    for element in satellites.load_corrected_elements(directory):
        age = element.age_days(now)
        rows.append(
            {
                "norad_id": element.norad_id,
                "name": element.name,
                "epoch": element.epoch.strftime("%Y-%m-%d %H:%M"),
                "age_days": age,
                "too_old": abs(age) > satellites.MAX_ELEMENT_AGE_DAYS,
                "enabled": selection.corrected_enabled(element.norad_id),
                "in_use": element.norad_id in in_use,
            }
        )
    rows.sort(key=lambda row: str(row["name"]))
    return rows


def _element_files(directory: Path) -> list[Path]:
    """The files that decide the satellites and their passes."""
    files = [
        satellites.group_file(group, directory)
        for group in satellites.selected_groups(directory)
    ]
    files.append(satellites.user_file(directory))
    files.append(satellites.corrected_file(directory))
    files.append(satellites.user_mag_file(directory))
    files.append(satellites.selection_file(directory))
    return files


def _files_key(directory: Path) -> tuple:
    """The name, the time and the size of each file. A change of a file or
    of the selection changes this key."""
    key = []
    for path in _element_files(directory):
        try:
            stat = path.stat()
        except OSError:
            continue
        key.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(key)


@dataclass(frozen=True)
class PassRow:
    norad_id: int
    name: str
    item: satellites.SatPass


@dataclass(frozen=True)
class PassInputs:
    """The time, the place and the files of a pass computation."""

    computed: datetime.datetime
    lat: float
    lon: float
    files: tuple


def _good_for(
    inputs: PassInputs, now: datetime.datetime, location, files: tuple
) -> bool:
    """True when a computation with ``inputs`` is good for this request."""
    age = abs((now - inputs.computed).total_seconds())
    moved = (
        abs(inputs.lat - location.lat) > PASS_TABLE_MOVE_DEG
        or abs(inputs.lon - location.lon) > PASS_TABLE_MOVE_DEG
    )
    return age <= PASS_TABLE_SECONDS and not moved and inputs.files == files


@dataclass(frozen=True)
class PassTableResult:
    inputs: PassInputs
    timezone: str
    # Sorted by the rise time. See _rows_to_keep.
    rows: tuple[PassRow, ...]

    @property
    def computed(self) -> datetime.datetime:
        return self.inputs.computed

    def info(self) -> dict:
        return {
            "state": "ready",
            "computed": self.computed.isoformat(),
            "timezone": self.timezone,
            "min_alt": MIN_PASS_ALT_DEG,
            "hours": PASS_HOURS,
        }


def _rows_to_keep(
    rows: list[PassRow], computed: datetime.datetime
) -> tuple[PassRow, ...]:
    """The rows that a page can show while the table is good.

    Each visible pass stays, because the magnitude limit of a page can have
    any value. Of the other passes, the first PASS_TABLE_ROWS that end after
    the end of the good time stay, and each pass that rises before the last
    of them. So up to that time, the first PASS_TABLE_ROWS rows of "all
    passes" are the same as with the full result.
    """
    rows = sorted(rows, key=lambda row: row.item.rise)
    end = computed + datetime.timedelta(seconds=PASS_TABLE_SECONDS)
    late = [row for row in rows if row.item.set >= end]
    if len(late) <= PASS_TABLE_ROWS:
        return tuple(rows)
    last_rise = late[PASS_TABLE_ROWS - 1].item.rise
    return tuple(row for row in rows if row.item.visible or row.item.rise <= last_rise)


def compute_pass_table(
    now: datetime.datetime, location, directory: Path = satellite_data_dir
) -> PassTableResult:
    """The passes of the selected satellites in the next PASS_HOURS."""
    files = _files_key(directory)
    user_mags = satellites.load_user_mags(directory)
    tracked = []
    for element in satellites.load_all_elements(now, directory):
        try:
            tracked.append(
                satellites.TrackedSatellite.from_elements(element, user_mags)
            )
        except ValueError:
            continue
    topos = satellites.observer_topos(location.lat, location.lon, location.altitude)
    start = now - datetime.timedelta(minutes=15)
    found = satellites.find_passes_many(
        tracked, topos, start, PASS_HOURS, MIN_PASS_ALT_DEG
    )
    rows = [
        PassRow(sat.norad_id, sat.name, item)
        for sat, items in zip(tracked, found)
        for item in items
    ]
    return PassTableResult(
        inputs=PassInputs(now, location.lat, location.lon, files),
        timezone=location.timezone or "UTC",
        rows=_rows_to_keep(rows, now),
    )


def _start_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True).start()


class PassTable:
    """The pass table of the web server, in the memory of its process.

    A request gets the table when it is good: less than PASS_TABLE_SECONDS
    old, for the same element files and selection, and for a location less
    than PASS_TABLE_MOVE_DEG away. Otherwise the request starts a
    computation in a background thread and gets the state "calculating".
    Only one computation runs at a time. A computation that fails gives the
    state "error" until the inputs change or the time limit ends.
    """

    def __init__(
        self,
        directory: Path = satellite_data_dir,
        start_thread: Callable[[Callable[[], None]], None] = _start_thread,
        compute: Callable[..., PassTableResult] = compute_pass_table,
    ):
        self.directory = directory
        self._start_thread = start_thread
        self._compute = compute
        self._lock = threading.Lock()
        self._result: Optional[PassTableResult] = None
        self._failed: Optional[PassInputs] = None
        self._running = False

    def get(
        self, now: datetime.datetime, location
    ) -> tuple[str, Optional[PassTableResult]]:
        """The state ("ready", "calculating" or "error") and the table."""
        files = _files_key(self.directory)
        with self._lock:
            state = self._state(now, location, files)
            if state is not None:
                return state
            self._running = True
        self._start_thread(lambda: self._run(now, location, files))
        with self._lock:
            return self._state(now, location, files) or ("calculating", None)

    def _state(
        self, now: datetime.datetime, location, files: tuple
    ) -> Optional[tuple[str, Optional[PassTableResult]]]:
        """The answer to a request, or None when a computation must start.
        The caller holds the lock."""
        result = self._result
        if result is not None and _good_for(result.inputs, now, location, files):
            return "ready", result
        if self._running:
            return "calculating", None
        failed = self._failed
        if failed is not None and _good_for(failed, now, location, files):
            return "error", None
        return None

    def _run(self, now: datetime.datetime, location, files: tuple) -> None:
        result = None
        try:
            with Timer("Satellite pass table"):
                result = self._compute(now, location, self.directory)
        except Exception:  # the next request must be able to try again
            logger.exception("Satellite pass table failed")
        with self._lock:
            if result is None:
                self._failed = PassInputs(now, location.lat, location.lon, files)
            else:
                self._result = result
                self._failed = None
            self._running = False


_pass_tables: dict[Path, PassTable] = {}
_pass_tables_lock = threading.Lock()


def pass_table(directory: Path = satellite_data_dir) -> PassTable:
    """The pass table of ``directory``, one for each process."""
    with _pass_tables_lock:
        table = _pass_tables.get(directory)
        if table is None:
            table = PassTable(directory)
            _pass_tables[directory] = table
        return table


def _has_location(location) -> bool:
    return location is not None and bool(getattr(location, "lock", False))


def upcoming_passes(
    now: datetime.datetime,
    location,
    visible_only: bool = True,
    directory: Path = satellite_data_dir,
    max_mag: Optional[float] = None,
    limit: int = PASS_TABLE_ROWS,
    table: Optional[PassTable] = None,
) -> tuple[list, Optional[dict]]:
    """The rows of the pass table and the data of the table.

    The data is None without a location. Its "state" is "ready",
    "calculating" or "error". Only a ready table has rows.
    """
    if not _has_location(location):
        return [], None
    if table is None:
        table = pass_table(directory)
    state, result = table.get(now, location)
    if result is None:
        return [], {"state": state}
    zone = _zone(result.timezone)
    rows = []
    for row in result.rows:
        item = row.item
        if item.set < now or (visible_only and not item.visible):
            continue
        if max_mag is not None and (item.min_mag is None or item.min_mag > max_mag):
            continue
        data = item.to_dict()
        data.update(norad_id=row.norad_id, name=row.name)
        rows.append(format_pass(data, zone))
        if len(rows) >= limit:
            break
    return rows, result.info()


def add_elements(
    text: str,
    name: str = "",
    norad: str = "",
    directory: Path = satellite_data_dir,
    std_mag: str = "",
) -> tuple[list[satellites.SatElements], list[str]]:
    """Read pasted text and a NORAD number, and save what is valid."""
    found: list[satellites.SatElements] = []
    errors: list[str] = []
    if text.strip():
        try:
            parsed, parse_errors = satellites.parse_elements(text, "user")
            found.extend(parsed)
            errors.extend(parse_errors)
        except satellites.ElementParseError as exc:
            errors.append(str(exc))
    if norad.strip():
        try:
            number = int(norad)
        except ValueError:
            number = 0
        if number <= 0:
            errors.append(f"not a NORAD number: {norad}")
        else:
            try:
                found.extend(satellites.fetch_by_norad(number))
            except satellites.ElementParseError:
                errors.append(f"CelesTrak has no elements for NORAD {number}")
            except Exception as exc:  # network errors of many types
                errors.append(f"CelesTrak: {exc}")
    name = name.strip()
    if name and len(found) == 1:
        element = found[0]
        found = [
            satellites.SatElements(
                name[:40], element.norad_id, element.line1, element.line2, "user"
            )
        ]
    if found:
        satellites.save_user_elements(found, directory)
    if std_mag.strip() and found:
        try:
            value = float(std_mag)
        except ValueError:
            value = math.nan
        if math.isfinite(value):
            for element in found:
                satellites.save_user_mag(element.norad_id, value, directory)
        else:
            errors.append(f"not a magnitude: {std_mag}")
    return found, errors


def set_enabled(
    kind: str, name: str, enabled: bool, directory: Path = satellite_data_dir
) -> None:
    """Select a group, or enable or disable one satellite of the user.

    Raises ValueError when the group or the number is not known.
    """
    if kind == "group":
        satellites.set_group_enabled(name, enabled, directory)
    elif kind == "user":
        satellites.set_user_enabled(int(name), enabled, directory)
    elif kind == "corrected":
        satellites.set_corrected_enabled(int(name), enabled, directory)
    else:
        raise ValueError(f"not a group or a satellite: {kind}")


def download_if_missing(
    group: str, now: datetime.datetime, directory: Path = satellite_data_dir
) -> Optional[satellites.GroupRefresh]:
    """Download a selected group that has no file.

    Returns None when the group is not selected or its file exists.
    """
    if not satellites.load_selection(directory).group_enabled(group):
        return None
    if satellites.group_file(group, directory).exists():
        return None
    return satellites.refresh_groups(now, True, directory, groups=(group,))


def refresh_message(result: satellites.GroupRefresh) -> tuple[str, str]:
    """The message and the error text for the result of a forced download."""
    if result.status == "busy":
        return "", "A download runs now. Try again in a minute."
    if result.status == "no_groups":
        return "", "No group is selected."
    errors = []
    if result.failed:
        errors.append("Download failed: " + ", ".join(result.failed) + ".")
    for group, seconds in result.refused:
        minutes = math.ceil(seconds / 60.0)
        errors.append(
            f"The last download of {group} is too recent. Wait {minutes} min."
        )
    message = ""
    if result.downloaded:
        message = "Downloaded: " + ", ".join(result.downloaded)
    elif result.status == "current":
        message = "The element sets are recent."
    return message, " ".join(errors)


def _duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    minutes, rest = divmod(int(seconds), 60)
    if minutes >= 60:
        return f"{minutes // 60} h {minutes % 60:02d} min"
    return f"{minutes} min {rest:02d} s"


def sky_now(
    now: datetime.datetime,
    location,
    directory: Path = satellite_data_dir,
) -> Optional[list]:
    """The enabled satellites above the horizon, the highest first.

    Returns None when the PiFinder has no location.
    """
    if location is None or not getattr(location, "lock", False):
        return None
    user_mags = satellites.load_user_mags(directory)
    tracked = []
    for element in satellites.load_all_elements(now, directory):
        try:
            tracked.append(
                satellites.TrackedSatellite.from_elements(element, user_mags)
            )
        except ValueError:
            continue
    topos = satellites.observer_topos(location.lat, location.lon, location.altitude)
    looks = satellites.look_many(tracked, topos, now)
    up = [(sat, look) for sat, look in zip(tracked, looks) if look.alt > 0]
    up.sort(key=lambda pair: -pair[1].alt)
    until_set = satellites.seconds_until_set([sat for sat, _look in up], topos, now)
    rows = []
    for (sat, look), seconds in zip(up, until_set):
        rows.append(
            {
                "norad_id": sat.norad_id,
                "name": sat.name,
                "alt": look.alt,
                "az": look.az,
                "dir": satellites.compass(look.az),
                "mag": look.mag,
                "sunlit": look.sunlit,
                "visible": look.visible,
                "sets_in_seconds": seconds,
                "sets_in": _duration(seconds),
            }
        )
    return rows


def satellite_detail(
    norad_id: int,
    now: datetime.datetime,
    location,
    days: float = 3.0,
    directory: Path = satellite_data_dir,
) -> Optional[dict]:
    elements = {
        e.norad_id: e
        for e in satellites.load_all_elements(now, directory, include_disabled=True)
    }.get(norad_id)
    if elements is None:
        return None
    enabled = any(
        e.norad_id == norad_id for e in satellites.load_all_elements(now, directory)
    )
    sat = satellites.TrackedSatellite.from_elements(
        elements, satellites.load_user_mags(directory)
    )
    result = {
        "norad_id": norad_id,
        "name": sat.name,
        "source": elements.source,
        "std_mag": sat.std_mag,
        "epoch": elements.epoch.strftime("%Y-%m-%d %H:%M UTC"),
        "age_days": elements.age_days(now),
        "line1": elements.line1,
        "line2": elements.line2,
        "enabled": enabled,
        "now": None,
        "passes": [],
    }
    if location is None or not getattr(location, "lock", False):
        return result
    zone = _zone(location.timezone)
    topos = satellites.observer_topos(location.lat, location.lon, location.altitude)
    look = satellites.look(sat, topos, now)
    result["now"] = {
        "alt": look.alt,
        "az": look.az,
        "dir": satellites.compass(look.az),
        "range_km": look.range_km,
        "mag": look.mag,
        "sunlit": look.sunlit,
        "visible": look.visible,
        "ra": look.ra,
        "dec": look.dec,
        "rate_arcmin_s": 60.0
        * math.hypot(look.ra_rate * math.cos(math.radians(look.dec)), look.dec_rate),
    }
    if days > 0:
        result["passes"] = [
            format_pass(item.to_dict(), zone)
            for item in satellites.find_passes(sat, topos, now, days * 24.0)
        ]
    return result
