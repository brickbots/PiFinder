"""Follow a moving target with a goto mount.

A moving target is anything that gives its position and its rates at a
time: a satellite, a Solar System body, or a comet or an asteroid as a list
of position samples. ``TargetFollow`` is the plan of the follow, the same
for all of them. The mount control calls it and moves the mount.

A satellite crosses the sky in a few minutes, so a single goto is too late
when it ends. The follow of a fast target works in stages:

1. AIM: goto the position where the target will be after the expected
   slew time (the lead).
2. WAIT: the mount is there first. Wait until the target arrives.
3. TRACK: set custom track rates equal to the target motion and update
   them every second. If the error grows too large, aim again.
4. PASS: a mount without custom track rates holds the aim point. The
   target crosses the eyepiece. When it is past, aim again.

A slow target (a comet, an asteroid, a planet) has no lead and no WAIT: the
goto ends on the target, then TRACK or PASS starts.

Each slew measures its duration, and the next lead uses it. Positions are
topocentric RA/Dec of date (JNow), the frame of the mount.

The user can correct the path during the follow (``TargetFollow.nudge``).
The prediction of a satellite is mostly wrong along its track, because old
elements give a wrong time. So the part of a correction along the track
becomes a time offset of the elements, and only the rest is a position
offset. The corrected elements are a new TLE (``shift_elements``).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Protocol, Sequence

from skyfield.api import wgs84

from PiFinder import satellites
from PiFinder.calc_utils import sf_utils

# Lead of the first slew to a fast target, before a slew time is measured.
DEFAULT_LEAD_S = 20.0
MIN_LEAD_S = 5.0
MAX_LEAD_S = 90.0
# The lead is this factor times the measured slew time.
LEAD_MARGIN = 1.3
# A target faster than this needs a lead and a wait (degrees per second).
FAST_DEG_S = 0.005
# In TRACK, aim again when the mount is this far from the target.
TRACK_MAX_ERROR_DEG = 0.5
# In PASS, aim again when the target is this far from the mount: this
# angle, or the motion of the target in PASS_SECONDS if that is less.
PASS_DISTANCE_DEG = 1.0
PASS_SECONDS = 60.0
PASS_MIN_DISTANCE_DEG = 0.02
# The follow ends when the target is lower than this.
MIN_ALT_DEG = 5.0
# Seconds between two track rate updates.
RATE_UPDATE_S = 1.0
# In TRACK, the rates remove an offset to the target in about this time,
# at most this fast.
CORRECTION_S = 5.0
MAX_CORRECTION_DEG_S = 0.1
# Largest user correction: seconds along the track, degrees across it.
MAX_TIME_OFFSET_S = 120.0
# A smaller time offset is no correction of the elements.
MIN_TIME_OFFSET_S = 0.05
MAX_OFFSET_DEG = 5.0

SIDEREAL_DEG_PER_DAY = 360.98564736629
# A target whose motion differs from a fixed point in alt-az by less than
# this (degrees per second, 1.8"/s) stays in view with tracking off. A
# geostationary satellite is such a target.
GROUND_FIXED_DEG_S = 0.0005
UNIX_EPOCH_JD = 2440587.5
J2000_JD = 2451545.0
GMST_AT_J2000_DEG = 280.46061837


class FollowStage(Enum):
    AIM = "aim"
    WAIT = "wait"
    TRACK = "track"
    PASS = "pass"


@dataclass(frozen=True)
class FollowPoint:
    """A target at one time, in the frame of the mount."""

    ra: float  # degrees, JNow
    dec: float
    ra_rate: float  # degrees per second
    dec_rate: float
    alt: float

    @property
    def speed(self) -> float:
        """Motion on the sky in degrees per second."""
        return math.hypot(
            self.ra_rate * math.cos(math.radians(self.dec)), self.dec_rate
        )


def ground_fixed(point: FollowPoint) -> bool:
    """True when the target is almost fixed in alt-az: its RA grows at the
    sidereal rate and its Dec stays the same."""
    sidereal = SIDEREAL_DEG_PER_DAY / 86400.0
    off_ra = (point.ra_rate - sidereal) * math.cos(math.radians(point.dec))
    return math.hypot(off_ra, point.dec_rate) < GROUND_FIXED_DEG_S


class MovingTarget(Protocol):
    """A target of a follow. A target with a ``shifted(seconds)`` method can
    also give the same target on its track, that many seconds ahead."""

    name: str

    def point(self, unix_time: float) -> FollowPoint: ...


def wrap_degrees(angle: float) -> float:
    """An angle difference in the range -180 to 180 degrees."""
    return (angle + 540.0) % 360.0 - 180.0


def angular_distance(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    cos_d = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(
        r1 - r2
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_d))))


def altitude(ra: float, dec: float, unix_time: float, lat: float, lon: float) -> float:
    """Altitude in degrees of a JNow position, without refraction."""
    days = unix_time / 86400.0 + UNIX_EPOCH_JD - J2000_JD
    hour_angle = GMST_AT_J2000_DEG + SIDEREAL_DEG_PER_DAY * days + lon - ra
    lat_r, dec_r, ha_r = map(math.radians, (lat, dec, hour_angle))
    sin_alt = math.sin(lat_r) * math.sin(dec_r) + math.cos(lat_r) * math.cos(
        dec_r
    ) * math.cos(ha_r)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))


def _skyfield_point(apparent_at, unix_time: float, step_s: float) -> FollowPoint:
    """The point of a skyfield target: position now, rates from the position
    ``step_s`` later. ``apparent_at(times)`` gives the topocentric position."""
    dt = datetime.fromtimestamp(unix_time, tz=timezone.utc)
    times = sf_utils.ts.from_datetimes([dt, dt + timedelta(seconds=step_s)])
    position = apparent_at(times)
    ra, dec, _distance = position.radec(epoch="date")
    alt, _az, _range = position.altaz()
    ra_deg = ra._degrees
    dec_deg = dec.degrees
    return FollowPoint(
        ra=float(ra_deg[0]) % 360.0,
        dec=float(dec_deg[0]),
        ra_rate=float(wrap_degrees(ra_deg[1] - ra_deg[0]) / step_s),
        dec_rate=float((dec_deg[1] - dec_deg[0]) / step_s),
        alt=float(alt.degrees[0]),
    )


def shift_elements(
    elements: satellites.SatElements, seconds: float
) -> satellites.SatElements:
    """The elements of the same orbit with the satellite ``seconds`` ahead.

    Only the mean anomaly changes, by the mean motion times ``seconds``.
    This is the usual correction of old elements: the orbit plane is right,
    the place in the orbit is not.
    """
    line2 = elements.line2
    mean_anomaly = float(line2[43:51])
    revs_per_day = float(line2[52:63])
    mean_anomaly = (mean_anomaly + revs_per_day * 360.0 * seconds / 86400.0) % 360.0
    body = f"{line2[:43]}{mean_anomaly:8.4f}{line2[51:68]}"
    line2 = f"{body}{satellites.tle_checksum(body)}"
    return satellites.SatElements(
        elements.name, elements.norad_id, elements.line1, line2, elements.source
    )


class SatelliteTarget:
    """An Earth satellite from its elements."""

    RATE_STEP_S = 1.0

    def __init__(
        self,
        elements: satellites.SatElements,
        lat: float,
        lon: float,
        altitude_m: float,
    ):
        self.elements = elements
        self.name = elements.name
        self._site = (lat, lon, altitude_m)
        self._difference = elements.to_earth_satellite() - satellites.observer_topos(
            lat, lon, altitude_m
        )

    def point(self, unix_time: float) -> FollowPoint:
        return _skyfield_point(self._difference.at, unix_time, self.RATE_STEP_S)

    def shifted(self, seconds: float) -> "SatelliteTarget":
        return SatelliteTarget(shift_elements(self.elements, seconds), *self._site)


class BodyTarget:
    """A body of the ephemeris: the Moon, the Sun or a planet. The position
    is topocentric, so the parallax of the Moon is in it."""

    RATE_STEP_S = 60.0

    def __init__(self, body: str, lat: float, lon: float, altitude_m: float):
        bodies = dict(zip(sf_utils.planet_names, sf_utils.planets))
        if body.upper() not in bodies:
            raise ValueError(f"unknown body {body!r}")
        self.name = body.capitalize()
        self._body = bodies[body.upper()]
        self._observer = sf_utils.eph["earth"] + wgs84.latlon(lat, lon, altitude_m)

    def point(self, unix_time: float) -> FollowPoint:
        return _skyfield_point(
            lambda times: self._observer.at(times).observe(self._body).apparent(),
            unix_time,
            self.RATE_STEP_S,
        )


class SampledTarget:
    """A target given as position samples (unix time, RA, Dec in JNow
    degrees), in time order. Used for comets and asteroids: the process that
    has the orbit computes the samples, the mount process only interpolates.
    After the last sample the target continues at the last rates."""

    def __init__(
        self,
        name: str,
        samples: Sequence[tuple[float, float, float]],
        lat: float,
        lon: float,
    ):
        if len(samples) < 2:
            raise ValueError("a sampled target needs two samples or more")
        self.name = name
        self._samples = sorted(
            (float(t), float(ra), float(dec)) for t, ra, dec in samples
        )
        self._times = [sample[0] for sample in self._samples]
        if any(b <= a for a, b in zip(self._times, self._times[1:])):
            raise ValueError("two samples have the same time")
        self._lat, self._lon = lat, lon

    def point(self, unix_time: float) -> FollowPoint:
        index = bisect_right(self._times, unix_time) - 1
        index = max(0, min(len(self._samples) - 2, index))
        t0, ra0, dec0 = self._samples[index]
        t1, ra1, dec1 = self._samples[index + 1]
        ra_rate = wrap_degrees(ra1 - ra0) / (t1 - t0)
        dec_rate = (dec1 - dec0) / (t1 - t0)
        ra = (ra0 + ra_rate * (unix_time - t0)) % 360.0
        dec = max(-90.0, min(90.0, dec0 + dec_rate * (unix_time - t0)))
        return FollowPoint(
            ra,
            dec,
            ra_rate,
            dec_rate,
            altitude(ra, dec, unix_time, self._lat, self._lon),
        )


def target_from_command(command: dict, location) -> MovingTarget:
    """The target of a ``follow_target`` command.

    ``kind`` is "satellite" (with name, norad_id, line1, line2), "body"
    (with body: "moon", "sun", "jupiter", ...) or "samples" (with name and
    samples). Raises KeyError or ValueError for a bad command.
    """
    kind = command["kind"]
    lat, lon, altitude_m = location.lat, location.lon, location.altitude
    if kind == "satellite":
        elements = satellites.SatElements(
            command.get("name", "Satellite"),
            int(command.get("norad_id", 0)),
            command["line1"],
            command["line2"],
        )
        return SatelliteTarget(elements, lat, lon, altitude_m)
    if kind == "body":
        return BodyTarget(command["body"], lat, lon, altitude_m)
    if kind == "samples":
        return SampledTarget(
            command.get("name", "Target"), command["samples"], lat, lon
        )
    raise ValueError(f"unknown target kind {kind!r}")


class TargetFollow:
    """The plan of a follow. The mount control calls it and moves the mount."""

    def __init__(self, target: MovingTarget, now: float):
        self.target = target
        self.name = target.name
        self._base = target
        # The user correction: seconds along the track of a fast target that
        # can shift, degrees across the track, and degrees north and east
        # for every other target.
        self.time_offset_s = 0.0
        self.cross_deg = 0.0
        self.offset_north = 0.0
        self.offset_east = 0.0
        self.fast = target.point(now).speed > FAST_DEG_S
        self.lead_s = DEFAULT_LEAD_S if self.fast else 0.0
        self.stage = FollowStage.AIM
        self.aim_time: Optional[float] = None
        self.aim_ra: Optional[float] = None
        self.aim_dec: Optional[float] = None
        self.slew_started: Optional[float] = None
        self.last_rate_update = 0.0
        self.aim_count = 0

    # -- the corrected path -------------------------------------------------

    def point(self, unix_time: float) -> FollowPoint:
        """The target with the user correction."""
        point = self.target.point(unix_time)
        north, east = self.offset_north, self.offset_east
        if self.cross_deg and point.speed > 0.0:
            # Unit vector across the track: the motion turned 90 degrees.
            cos_dec = math.cos(math.radians(point.dec))
            north += self.cross_deg * point.ra_rate * cos_dec / point.speed
            east -= self.cross_deg * point.dec_rate / point.speed
        if not north and not east:
            return point
        dec = max(-89.9, min(89.9, point.dec + north))
        ra = (point.ra + east / math.cos(math.radians(dec))) % 360.0
        return FollowPoint(ra, dec, point.ra_rate, point.dec_rate, point.alt)

    @property
    def corrected(self) -> bool:
        return bool(
            self.time_offset_s
            or self.cross_deg
            or self.offset_north
            or self.offset_east
        )

    def nudge(self, north_deg: float, east_deg: float, now: float) -> None:
        """Move the path by this angle on the sky: the target is north_deg
        north and east_deg east of the prediction."""
        point = self.target.point(now)
        shifted = getattr(self._base, "shifted", None)
        if shifted is None or point.speed <= FAST_DEG_S:
            self.offset_north = _clamp(self.offset_north + north_deg, MAX_OFFSET_DEG)
            self.offset_east = _clamp(self.offset_east + east_deg, MAX_OFFSET_DEG)
            return
        cos_dec = math.cos(math.radians(point.dec))
        along_north = point.dec_rate / point.speed
        along_east = point.ra_rate * cos_dec / point.speed
        along = north_deg * along_north + east_deg * along_east
        cross = north_deg * along_east - east_deg * along_north
        seconds = _clamp(self.time_offset_s + along / point.speed, MAX_TIME_OFFSET_S)
        if self.aim_time is not None:
            # A satellite that is ahead of the prediction arrives earlier.
            self.aim_time -= seconds - self.time_offset_s
        self.time_offset_s = seconds
        self.cross_deg = _clamp(self.cross_deg + cross, MAX_OFFSET_DEG)
        self.target = shifted(seconds)

    def corrected_elements(self) -> Optional[satellites.SatElements]:
        """The elements with the time offset of the user, or None."""
        if abs(self.time_offset_s) < MIN_TIME_OFFSET_S:
            return None
        return getattr(self.target, "elements", None)

    # -- stages -------------------------------------------------------------

    def aim(self, now: float) -> FollowPoint:
        """Start an AIM: the point where the target is after the lead."""
        self.aim_time = now + self.lead_s
        target = self.point(self.aim_time)
        self.aim_ra, self.aim_dec = target.ra, target.dec
        self.slew_started = now
        self.stage = FollowStage.AIM
        self.aim_count += 1
        return target

    def slew_done(self, now: float) -> None:
        """The mount is at the aim point: learn the slew time, then wait."""
        if self.fast and self.slew_started is not None:
            measured = now - self.slew_started
            self.lead_s = min(MAX_LEAD_S, max(MIN_LEAD_S, measured * LEAD_MARGIN))
        self.stage = FollowStage.WAIT

    def late(self, now: float) -> bool:
        """The fast target passed the aim point before the slew ended."""
        return self.fast and self.aim_time is not None and now > self.aim_time

    def arrived(self, now: float) -> bool:
        return self.aim_time is not None and now >= self.aim_time

    def seconds_to_arrival(self, now: float) -> float:
        return 0.0 if self.aim_time is None else max(0.0, self.aim_time - now)

    def rate_update_due(self, now: float) -> bool:
        if now - self.last_rate_update >= RATE_UPDATE_S:
            self.last_rate_update = now
            return True
        return False

    def pass_distance(self, point: FollowPoint) -> float:
        """In PASS: the angle between mount and target that starts a new aim."""
        return min(
            PASS_DISTANCE_DEG,
            max(PASS_MIN_DISTANCE_DEG, point.speed * PASS_SECONDS),
        )


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))
