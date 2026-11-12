"""Track rates of the mount: sidereal, lunar and solar.

The Moon moves east about 0.5 degrees per hour, the Sun about 1 degree per
day. A mount that tracks at the sidereal rate lets the Moon drift out of a
high power field in minutes. INDI has the track modes TRACK_LUNAR and
TRACK_SOLAR for this. For a mount without them, ``body_rates`` gives the
motion of the Moon or the Sun for custom track rates.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from skyfield.api import wgs84

from PiFinder.calc_utils import sf_utils

SIDEREAL = "sidereal"
LUNAR = "lunar"
SOLAR = "solar"
AUTO = "auto"
TRACK_RATES = (SIDEREAL, LUNAR, SOLAR)
# Config option of the track rate setting: AUTO or one of TRACK_RATES.
OPTION = "mount_control_track_rate"
# The INDI switch of TELESCOPE_TRACK_MODE for each track rate.
INDI_TRACK_MODES = {
    SIDEREAL: "TRACK_SIDEREAL",
    LUNAR: "TRACK_LUNAR",
    SOLAR: "TRACK_SOLAR",
}
# The ephemeris body of each non-sidereal rate.
BODIES = {LUNAR: "moon", SOLAR: "sun"}
# Interval of the rate measurement, and of the custom rate updates.
RATE_STEP_S = 60.0


def rate_for_object(setting: str, obj) -> str:
    """The track rate of a goto to ``obj``.

    With the setting AUTO the Moon gets the lunar rate, the Sun the solar
    rate and every other object the sidereal rate.
    """
    if setting in TRACK_RATES:
        return setting
    if getattr(obj, "catalog_code", "") == "PL":
        names = [str(name).lower() for name in getattr(obj, "names", [])]
        if "moon" in names:
            return LUNAR
        if "sun" in names:
            return SOLAR
    return SIDEREAL


def body_rates(
    rate: str, lat: float, lon: float, altitude_m: float, dt: datetime
) -> Optional[tuple[float, float]]:
    """RA and Dec rates of date in degrees per second for LUNAR or SOLAR,
    topocentric, so the parallax of the Moon is in it. None for SIDEREAL."""
    body = BODIES.get(rate)
    if body is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    observer = sf_utils.eph["earth"] + wgs84.latlon(lat, lon, altitude_m)
    target = sf_utils.eph[body]
    times = sf_utils.ts.from_datetimes([dt, dt + timedelta(seconds=RATE_STEP_S)])
    ra, dec, _distance = (
        observer.at(times).observe(target).apparent().radec(epoch="date")
    )
    ra_step = (ra._degrees[1] - ra._degrees[0] + 540.0) % 360.0 - 180.0
    return (
        float(ra_step / RATE_STEP_S),
        float((dec.degrees[1] - dec.degrees[0]) / RATE_STEP_S),
    )
