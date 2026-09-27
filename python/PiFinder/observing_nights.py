#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Observing nights: the grouping the observations UI is built on.

A *session* is one PiFinder software run — ``UIModule.__uuid__`` is minted
once per process — so a restart, a crash or a reboot mid-evening starts a
new one. An *observing night* is what the observer actually experienced:
every observation made between one noon and the next, in the timezone the
observations were logged in, however many runs it took.

The noon-to-noon boundary is what puts an evening and its after-midnight
hours in the same night, labelled by the evening's date. It also means a
session that runs past noon splits across two nights, which is correct.

Timestamps in the DB are absolute epochs (``local_datetime()`` is
timezone-aware, so its ``.timestamp()`` is a true instant); the session's
timezone is what turns them back into the observer's clock. Everything
here is pure — no DB, no I/O — so the bucketing is testable on its own.
"""

import datetime
import json
from typing import Any, Dict, List, Optional, Sequence

import pytz

from PiFinder import timez

# Nights run noon to noon: an observation is attributed to the day its
# local clock reads once this much is subtracted.
NIGHT_BOUNDARY_HOURS = 12

# Format of a night's key, and the date format of the legacy log rows that
# stored a rendered datetime instead of an epoch.
NIGHT_KEY_FORMAT = "%Y-%m-%d"
LEGACY_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def zone_for(tzname: Optional[str]) -> datetime.tzinfo:
    """The observer's zone, falling back to UTC when it isn't usable.

    Mirrors ``SharedStateObj.local_datetime()``: an unknown or missing
    zone must not stop an observation from being displayed, it just gets
    displayed in UTC.
    """
    if not tzname:
        return pytz.utc
    try:
        return pytz.timezone(tzname)
    except (pytz.exceptions.UnknownTimeZoneError, AttributeError):
        return pytz.utc


def coerce_epoch(value: Any) -> Optional[float]:
    """A log row's time as a POSIX timestamp, or None if unreadable.

    Current rows store an epoch. Some early rows stored a rendered UTC
    datetime string instead, which the DB layer has always had to paper
    over; both are accepted here so old logs keep their place in a night.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        parsed = timez.parse(text, LEGACY_TIME_FORMAT)
    except ValueError:
        return None
    return pytz.utc.localize(parsed).timestamp()


def local_datetime(epoch: float, tzname: Optional[str]) -> datetime.datetime:
    """An epoch as the observer's wall clock."""
    return timez.utc_from_timestamp(epoch).astimezone(zone_for(tzname))


def night_key(epoch: float, tzname: Optional[str]) -> str:
    """The night an instant belongs to, as its local ``YYYY-MM-DD``.

    Shifting back by twelve hours before taking the date is what keeps an
    observation at 01:30 on the evening that led to it.
    """
    local = local_datetime(epoch, tzname)
    shifted = local - datetime.timedelta(hours=NIGHT_BOUNDARY_HOURS)
    return shifted.strftime(NIGHT_KEY_FORMAT)


def _sqm_summary(readings: List[float]) -> Optional[Dict[str, float]]:
    """Median and range of a night's sky-brightness readings."""
    if not readings:
        return None
    ordered = sorted(readings)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        median = ordered[middle]
    else:
        median = (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "median": round(median, 2),
        "min": round(ordered[0], 2),
        "max": round(ordered[-1], 2),
        "count": len(ordered),
    }


def parse_notes(notes: Any) -> Dict[str, Any]:
    """An observation's notes as a dict, whatever shape they arrive in.

    The column holds JSON text, but callers hand over both the raw column
    and already-parsed notes; anything unreadable is treated as empty
    rather than failing a page render.
    """
    if isinstance(notes, dict):
        return notes
    if not notes:
        return {}
    try:
        parsed = json.loads(notes)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def observation_sqm(notes: Any) -> Optional[float]:
    """The sky brightness recorded with one observation, if any.

    Notes are a JSON blob whose shape has changed over time, and only
    schema 3 onwards carries a reading — anything else simply has none.
    """
    sqm = parse_notes(notes).get("sqm")
    if not isinstance(sqm, dict):
        return None
    value = sqm.get("value")
    if value is None or not sqm.get("source") or sqm.get("source") == "None":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def group_into_nights(rows: Sequence[Any]) -> List[Dict[str, Any]]:
    """Bucket observation rows into nights, most recent first.

    Each row needs ``obs_time_local`` and the session context the DB join
    supplies (``timezone``, ``lat``, ``lon``, ``session_uid``); ``notes``
    is used for the night's sky-brightness summary when present. Rows with
    an unreadable timestamp are dropped rather than being given a
    misleading place in the log.
    """
    nights: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        record = dict(row)
        epoch = coerce_epoch(record.get("obs_time_local"))
        if epoch is None:
            continue

        tzname = record.get("timezone")
        key = night_key(epoch, tzname)
        night = nights.get(key)
        if night is None:
            night = {
                "night_key": key,
                "timezone": tzname,
                "lat": record.get("lat"),
                "lon": record.get("lon"),
                "start_epoch": epoch,
                "end_epoch": epoch,
                "observations": 0,
                "session_uids": [],
                "sqm_readings": [],
            }
            nights[key] = night

        night["observations"] += 1
        night["start_epoch"] = min(night["start_epoch"], epoch)
        night["end_epoch"] = max(night["end_epoch"], epoch)

        session_uid = record.get("session_uid")
        if session_uid is not None and session_uid not in night["session_uids"]:
            night["session_uids"].append(session_uid)

        sqm = observation_sqm(record.get("notes"))
        if sqm is not None:
            night["sqm_readings"].append(sqm)

    for night in nights.values():
        tzname = night["timezone"]
        # The night is named for the evening it began, which is not the
        # date of its first observation when that observation came after
        # midnight.
        night["date"] = timez.parse(night["night_key"], NIGHT_KEY_FORMAT).date()
        night["start"] = local_datetime(night["start_epoch"], tzname)
        night["end"] = local_datetime(night["end_epoch"], tzname)
        night["span_hours"] = (night["end_epoch"] - night["start_epoch"]) / 3600
        night["sessions"] = len(night["session_uids"])
        night["sqm"] = _sqm_summary(night.pop("sqm_readings"))

    return sorted(nights.values(), key=lambda n: n["night_key"], reverse=True)
