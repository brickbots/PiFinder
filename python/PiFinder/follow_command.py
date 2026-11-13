"""The mount command that follows a catalog object which moves.

A satellite, a comet or an asteroid moves against the stars. The mount
process follows it (see target_follow.py) from a ``follow_target`` command.
The command has all the data of the target, because the mount process has
no catalogs: the elements of a satellite, or position samples of a comet or
an asteroid.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Optional

from PiFinder import asteroids, calc_utils, comets, satellite_catalog

logger = logging.getLogger("FollowCommand")

# Samples of a comet or an asteroid: this many, this far apart.
SAMPLE_COUNT = 5
SAMPLE_STEP = timedelta(minutes=30)
# A comet or an asteroid slower than this gets a normal goto: it stays in a
# high power field for hours.
FOLLOW_MIN_ARCSEC_PER_HOUR = 60.0


def follow_command(obj, dt: Optional[datetime]) -> Optional[dict]:
    """The follow_target command for ``obj``, or None for an object that
    needs a normal goto."""
    if satellite_catalog.is_satellite(obj):
        return _satellite_command(obj)
    if dt is None:
        return None
    code = getattr(obj, "catalog_code", "")
    try:
        if code == "CM":
            return _samples_command(obj, dt, comets.comet_track)
        if code == "MP":
            return _samples_command(obj, dt, asteroids.asteroid_track)
    except Exception:
        # Element files change with each download: a goto is better than
        # no move.
        logger.exception("No follow samples for %s", obj.display_name)
    return None


def _satellite_command(obj) -> Optional[dict]:
    catalog = satellite_catalog.active_catalog()
    tracked = catalog.tracked(obj.sequence) if catalog else None
    if tracked is None:
        return None
    elements = tracked.elements
    return {
        "type": "follow_target",
        "kind": "satellite",
        "norad_id": elements.norad_id,
        "name": elements.name,
        "line1": elements.line1,
        "line2": elements.line2,
    }


def _samples_command(obj, dt: datetime, track) -> Optional[dict]:
    key = obj.names[0] if obj.catalog_code == "CM" else obj.sequence
    times = [dt + SAMPLE_STEP * index for index in range(SAMPLE_COUNT)]
    positions = track(key, times)
    if len(positions) != len(times):
        return None
    samples = []
    for when, (ra, dec) in zip(times, positions):
        ra_now, dec_now = calc_utils.j2000_to_jnow(ra, dec, when)
        samples.append((when.timestamp(), float(ra_now), float(dec_now)))
    if _arcsec_per_hour(samples[0], samples[1]) < FOLLOW_MIN_ARCSEC_PER_HOUR:
        return None
    return {
        "type": "follow_target",
        "kind": "samples",
        "name": obj.names[0] if obj.names else obj.display_name,
        "samples": samples,
    }


def _arcsec_per_hour(first, second) -> float:
    (t0, ra0, dec0), (t1, ra1, dec1) = first, second
    d_ra = ((ra1 - ra0 + 540.0) % 360.0 - 180.0) * math.cos(math.radians(dec0))
    return math.hypot(d_ra, dec1 - dec0) * 3600.0 / ((t1 - t0) / 3600.0)
