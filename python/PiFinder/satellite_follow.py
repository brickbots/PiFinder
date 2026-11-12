"""Follow a satellite with a goto mount.

A satellite crosses the sky in a few minutes, so a single goto is too late
when it ends. The follow works in stages:

1. AIM: goto the position where the satellite will be after the expected
   slew time (the lead).
2. WAIT: the mount is there first. Wait until the satellite arrives.
3. TRACK: set custom track rates equal to the satellite motion and update
   them every second. If the error grows too large, aim again.
4. PASS: a mount without custom track rates holds the aim point. The
   satellite crosses the eyepiece. When it is past, aim again.

Each slew measures its duration, and the next lead uses it. Positions are
topocentric RA/Dec of date (JNow), the frame of the mount.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from PiFinder import satellites
from PiFinder.calc_utils import sf_utils

# Lead of the first slew, before a slew time is measured.
DEFAULT_LEAD_S = 20.0
MIN_LEAD_S = 5.0
MAX_LEAD_S = 90.0
# The lead is this factor times the measured slew time.
LEAD_MARGIN = 1.3
# In TRACK, aim again when the mount is this far from the satellite.
TRACK_MAX_ERROR_DEG = 0.5
# In PASS, aim again when the satellite is this far past the aim point.
PASS_DISTANCE_DEG = 1.0
# The follow ends when the satellite is lower than this.
MIN_ALT_DEG = 5.0
# Seconds between two track rate updates.
RATE_UPDATE_S = 1.0
# In TRACK, the rates remove an offset to the satellite in about this time,
# at most this fast.
CORRECTION_S = 5.0
MAX_CORRECTION_DEG_S = 0.1


class FollowStage(Enum):
    AIM = "aim"
    WAIT = "wait"
    TRACK = "track"
    PASS = "pass"


@dataclass(frozen=True)
class FollowPoint:
    """The satellite at one time, in the frame of the mount."""

    ra: float  # degrees, JNow
    dec: float
    ra_rate: float  # degrees per second
    dec_rate: float
    alt: float


def _angular_distance(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    cos_d = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(
        r1 - r2
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_d))))


class SatelliteFollow:
    """The plan of a follow. The mount control calls it and moves the mount."""

    def __init__(
        self,
        elements: satellites.SatElements,
        lat: float,
        lon: float,
        altitude_m: float,
        lead_s: float = DEFAULT_LEAD_S,
    ):
        self.elements = elements
        self.name = elements.name
        self._satellite = elements.to_earth_satellite()
        self._topos = satellites.observer_topos(lat, lon, altitude_m)
        self.lead_s = lead_s
        self.stage = FollowStage.AIM
        self.aim_time: Optional[float] = None
        self.aim_ra: Optional[float] = None
        self.aim_dec: Optional[float] = None
        self.slew_started: Optional[float] = None
        self.last_rate_update = 0.0
        self.aim_count = 0

    @classmethod
    def from_command(cls, command: dict, location) -> "SatelliteFollow":
        elements = satellites.SatElements(
            command.get("name", "Satellite"),
            int(command.get("norad_id", 0)),
            command["line1"],
            command["line2"],
        )
        return cls(elements, location.lat, location.lon, location.altitude)

    def point(self, unix_time: float) -> FollowPoint:
        dt = datetime.fromtimestamp(unix_time, tz=timezone.utc)
        times = sf_utils.ts.from_datetimes([dt, dt + timedelta(seconds=1.0)])
        topocentric = (self._satellite - self._topos).at(times)
        ra, dec, _distance = topocentric.radec(epoch="date")
        alt, _az, _range = topocentric.altaz()
        ra_deg = ra._degrees
        dec_deg = dec.degrees
        ra_step = (ra_deg[1] - ra_deg[0] + 540.0) % 360.0 - 180.0
        return FollowPoint(
            ra=float(ra_deg[0]) % 360.0,
            dec=float(dec_deg[0]),
            ra_rate=float(ra_step),
            dec_rate=float(dec_deg[1] - dec_deg[0]),
            alt=float(alt.degrees[0]),
        )

    # -- stages -------------------------------------------------------------

    def aim(self, now: float) -> FollowPoint:
        """Start an AIM: the point where the satellite is after the lead."""
        self.aim_time = now + self.lead_s
        target = self.point(self.aim_time)
        self.aim_ra, self.aim_dec = target.ra, target.dec
        self.slew_started = now
        self.stage = FollowStage.AIM
        self.aim_count += 1
        return target

    def slew_done(self, now: float) -> None:
        """The mount is at the aim point: learn the slew time, then wait."""
        if self.slew_started is not None:
            measured = now - self.slew_started
            self.lead_s = min(MAX_LEAD_S, max(MIN_LEAD_S, measured * LEAD_MARGIN))
        self.stage = FollowStage.WAIT

    def late(self, now: float) -> bool:
        """The satellite passed the aim point before the slew ended."""
        return self.aim_time is not None and now > self.aim_time

    def arrived(self, now: float) -> bool:
        return self.aim_time is not None and now >= self.aim_time

    def seconds_to_arrival(self, now: float) -> float:
        return 0.0 if self.aim_time is None else max(0.0, self.aim_time - now)

    def rate_update_due(self, now: float) -> bool:
        if now - self.last_rate_update >= RATE_UPDATE_S:
            self.last_rate_update = now
            return True
        return False

    def past_aim_point(self, now: float) -> bool:
        """In PASS: the satellite is far enough past the aim point."""
        if self.aim_ra is None or self.aim_dec is None:
            return True
        current = self.point(now)
        return _angular_distance(
            current.ra, current.dec, self.aim_ra, self.aim_dec
        ) > PASS_DISTANCE_DEG and self.arrived(now)

    def tracking_error(
        self, now: float, mount_ra: Optional[float], mount_dec: Optional[float]
    ) -> Optional[float]:
        if mount_ra is None or mount_dec is None:
            return None
        current = self.point(now)
        return _angular_distance(current.ra, current.dec, mount_ra, mount_dec)

    def too_low(self, now: float) -> bool:
        return self.point(now).alt < MIN_ALT_DEG
