"""Data for the satellite web pages.

The web server runs in its own process. It reads the element files and the
pass cache that the satellite catalog writes, and it computes the passes of
one satellite on request.
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path
from typing import Optional

import pytz

import PiFinder.satellites as satellites
from PiFinder.utils import satellite_data_dir


# The pass table on the web page lists passes this bright or brighter.
DEFAULT_MAX_MAG = 4.0


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


def group_status(now: datetime.datetime, directory: Path = satellite_data_dir) -> list:
    rows = []
    for group in satellites.CELESTRAK_GROUPS:
        path = satellites.group_file(group, directory)
        if path.exists():
            age_hours = (now.timestamp() - path.stat().st_mtime) / 3600.0
            count = len(satellites.read_tle_file(path, "celestrak"))
            rows.append({"group": group, "age_hours": age_hours, "count": count})
        else:
            rows.append({"group": group, "age_hours": None, "count": 0})
    return rows


def user_satellites(
    now: datetime.datetime, directory: Path = satellite_data_dir
) -> list:
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
            }
        )
    rows.sort(key=lambda row: str(row["name"]))
    return rows


def upcoming_passes(
    now: datetime.datetime,
    visible_only: bool = True,
    directory: Path = satellite_data_dir,
    max_mag: Optional[float] = None,
) -> tuple[list, Optional[dict]]:
    cache = satellites.read_pass_cache(directory)
    if cache is None:
        return [], None
    zone = _zone(cache.get("timezone"))
    rows = []
    for row in cache.get("passes", []):
        end = datetime.datetime.fromisoformat(row["set"])
        if end < now or (visible_only and not row["visible"]):
            continue
        if max_mag is not None and (row["min_mag"] is None or row["min_mag"] > max_mag):
            continue
        rows.append(format_pass(row, zone))
    return rows, cache


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
            found.extend(satellites.fetch_by_norad(int(norad)))
        except ValueError:
            errors.append(f"not a NORAD number: {norad}")
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
            for element in found:
                satellites.save_user_mag(element.norad_id, value, directory)
        except ValueError:
            errors.append(f"not a magnitude: {std_mag}")
    return found, errors


def satellite_detail(
    norad_id: int,
    now: datetime.datetime,
    location,
    days: float = 3.0,
    directory: Path = satellite_data_dir,
) -> Optional[dict]:
    elements = {
        e.norad_id: e for e in satellites.load_all_elements(now, directory)
    }.get(norad_id)
    if elements is None:
        return None
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
