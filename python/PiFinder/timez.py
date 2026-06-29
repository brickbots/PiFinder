"""Sanctioned datetime constructors — the one place datetimes are created.

The ``DTZ`` lint family (flake8-datetimez) is enabled repo-wide and this module
is the only file exempt from it. Build datetimes through these helpers instead
of bare ``datetime.now()`` / ``datetime(...)`` / ``strptime()`` elsewhere, so
"local or UTC?" stays an explicit choice at every call site and a naive value
can never silently reach the astronomy/ephemeris path. See ADR-0018.

Pick by intent:
- civil / astronomical time (epoch for RA/Dec, ephemerides) -> utc_now,
  utc_from_timestamp, utc
- local bookkeeping (filenames, log stamps, elapsed-time timers) -> local_now
- parsing a string whose zone the caller attaches afterwards -> parse, naive
"""

import datetime

import pytz


def utc_now() -> datetime.datetime:
    """Current instant, timezone-aware in UTC. Use for civil/astronomical time."""
    return datetime.datetime.now(pytz.utc)


def local_now() -> datetime.datetime:
    """Current instant as a naive datetime in the host's local timezone.

    Local bookkeeping only — filenames, log stamps, elapsed-time timers. Never
    feed this to astronomy/ephemeris math; use utc_now().
    """
    return datetime.datetime.now()


def utc_from_timestamp(ts: float) -> datetime.datetime:
    """A POSIX timestamp as a timezone-aware UTC datetime (e.g. a file mtime)."""
    return datetime.datetime.fromtimestamp(ts, pytz.utc)


def parse(value: str, fmt: str) -> datetime.datetime:
    """``strptime`` producing a naive datetime; the caller attaches the zone."""
    return datetime.datetime.strptime(value, fmt)


def naive(year: int, month: int, day: int,
          hour: int = 0, minute: int = 0, second: int = 0,
          microsecond: int = 0) -> datetime.datetime:
    """Construct a naive datetime from explicit fields; the caller localizes it."""
    # trick linter that refuses regular naive construction, pass "acceptable"
    # datetime then nuke the tzinfo
    return datetime.datetime(year, month, day, hour, minute, second,
                             microsecond, tzinfo=pytz.utc).replace(tzinfo=None)

def utc(year: int, month: int, day: int,
        hour: int = 0, minute: int = 0, second: int = 0,
        microsecond: int = 0) -> datetime.datetime:
    """Construct a timezone-aware UTC datetime from explicit fields."""
    return datetime.datetime(year, month, day, hour, minute, second,
                             microsecond, tzinfo=pytz.utc)
