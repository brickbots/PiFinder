"""The satellites in the field of the chart, at their live positions.

A satellite moves up to about one degree per second, so the positions of
the last catalog update (every 5 s) can be degrees off. The layer works in
two steps:

* A **batch**, at most every ``REFRESH_SECONDS``: the catalog positions
  (``SatelliteCatalog.sky_state``) select the candidates near the chart
  centre, with a margin for the motion since that update. One vectorized
  SGP4 call then gives each candidate its position now and
  ``TRACK_SECONDS`` later.
* A **frame**: each candidate moves along the straight line between those
  two positions to the time of the frame. This costs a few numpy operations
  for a few dozen satellites.

The catalog can hold more than 10,000 satellites (Starlink). The SGP4 call
of a batch has only the candidates, at most ``BATCH_CAP``.
"""

from __future__ import annotations

import datetime
import math
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

# The shortest time between two batches.
REFRESH_SECONDS = 0.25
# The time between the two positions of a batch. The track line on the
# chart shows the motion over this time.
TRACK_SECONDS = 10.0
# The fastest motion across the sky of a low satellite, in degrees per
# second. The ISS overhead moves about 1.1 degrees per second.
MAX_RATE_DEG_S = 1.2
# A batch looks this much wider than the chart, so a small slew does not
# need a new batch.
SEARCH_MARGIN_DEG = 2.0
# A satellite can be this much below the horizon in the catalog positions
# and still be a candidate. It covers the motion since the catalog update.
HORIZON_MARGIN_DEG = 2.0
# The most candidates in one batch, brightest first.
BATCH_CAP = 100
# The most satellites drawn in the field, brightest first.
FIELD_CAP = 10


@dataclass
class FieldSatellite:
    """A satellite in the field of the chart at the time of a frame."""

    obj: object  # the CompositeObject of the satellite catalog
    ra: float  # degrees, J2000
    dec: float
    ahead_ra: float  # the position TRACK_SECONDS later
    ahead_dec: float
    mag: float


@dataclass
class _Batch:
    made: float  # clock time
    time: datetime.datetime
    center: tuple[float, float]
    radius: float  # the chart radius of the batch
    search_radius: float
    mag_limit: float
    filtered: list
    objects: list
    mag: np.ndarray
    ra: np.ndarray  # (n, 2): now and TRACK_SECONDS later
    dec: np.ndarray
    alt: np.ndarray


def angular_sep_deg(ra1, dec1, ra2, dec2):
    """Great-circle separation in degrees. Works on numpy arrays."""
    d1 = np.radians(dec1)
    d2 = np.radians(dec2)
    cos_sep = np.sin(d1) * np.sin(d2) + np.cos(d1) * np.cos(d2) * np.cos(
        np.radians(np.asarray(ra2) - np.asarray(ra1))
    )
    return np.degrees(np.arccos(np.clip(cos_sep, -1.0, 1.0)))


class SatelliteLayer:
    """Finds the satellites in the field of the chart for each frame."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._batch: Optional[_Batch] = None
        # The filtered object list that _accepted was made from, and the
        # map of NORAD id to object of that list.
        self._filtered: Optional[list] = None
        self._accepted: dict = {}
        # The SGP4 calls of the batches, for the tests.
        self.batch_count = 0

    def reset(self) -> None:
        self._batch = None

    def field(
        self,
        catalog,
        filtered: list,
        center: tuple[float, float],
        radius: float,
        dt: datetime.datetime,
        mag_limit: float,
        exclude: frozenset = frozenset(),
    ) -> list[FieldSatellite]:
        """The satellites to draw for a frame at ``dt``.

        ``filtered`` holds the objects that the catalog filter accepts. The
        catalog gives a new list when the filter result changes. A satellite
        is drawn when it is above the horizon,
        within ``radius`` degrees of ``center``, in sunlight and not fainter
        than ``mag_limit``. The brightest ``FIELD_CAP`` are drawn. The NORAD
        ids in ``exclude`` are not drawn.
        """
        if filtered is not self._filtered:
            self._filtered = filtered
            self._accepted = {obj.sequence: obj for obj in filtered}
        batch = self._batch
        if self._batch_stale(batch, filtered, center, radius, mag_limit):
            batch = self._make_batch(catalog, filtered, center, radius, dt, mag_limit)
            self._batch = batch
        if batch is None or not batch.objects:
            return []
        return _select(batch, center, radius, dt, mag_limit, exclude)

    def _batch_stale(self, batch, filtered, center, radius, mag_limit) -> bool:
        if batch is None:
            return True
        if self._clock() - batch.made >= REFRESH_SECONDS:
            return True
        if (
            filtered is not batch.filtered
            or radius != batch.radius
            or mag_limit != batch.mag_limit
        ):
            return True
        moved = float(angular_sep_deg(center[0], center[1], *batch.center))
        return moved > batch.search_radius - radius - MAX_RATE_DEG_S * TRACK_SECONDS

    def _make_batch(
        self, catalog, filtered, center, radius, dt, mag_limit
    ) -> Optional[_Batch]:
        accepted = self._accepted
        state = catalog.sky_state(dt)
        if state is None or not len(state.norad_ids) or not accepted:
            return None
        age = abs((dt - state.time).total_seconds())
        motion = MAX_RATE_DEG_S * (age + REFRESH_SECONDS)
        # The live positions of a batch serve for TRACK_SECONDS of motion, so
        # the search also covers that.
        search_radius = (
            radius + SEARCH_MARGIN_DEG + motion + MAX_RATE_DEG_S * TRACK_SECONDS
        )
        with np.errstate(invalid="ignore"):
            near = (
                (state.alt > -(HORIZON_MARGIN_DEG + motion))
                & (state.mag <= mag_limit)
                & (
                    angular_sep_deg(center[0], center[1], state.ra, state.dec)
                    <= search_radius
                )
            )
        rows = np.flatnonzero(near)
        rows = rows[np.argsort(state.mag[rows], kind="stable")]
        objects = []
        ids = []
        mags = []
        for row in rows.tolist():
            norad = int(state.norad_ids[row])
            obj = accepted.get(norad)
            if obj is None:
                continue
            objects.append(obj)
            ids.append(norad)
            mags.append(float(state.mag[row]))
            if len(ids) >= BATCH_CAP:
                break
        self.batch_count += 1
        times = [dt, dt + datetime.timedelta(seconds=TRACK_SECONDS)]
        ra, dec, alt = catalog.live_tracks(ids, times)
        return _Batch(
            made=self._clock(),
            time=dt,
            center=center,
            radius=radius,
            search_radius=search_radius,
            mag_limit=mag_limit,
            filtered=filtered,
            objects=objects,
            mag=np.array(mags, dtype=float),
            ra=ra,
            dec=dec,
            alt=alt,
        )


def _select(batch, center, radius, dt, mag_limit, exclude) -> list[FieldSatellite]:
    """Move the batch to ``dt`` and keep the satellites in the field."""
    part = (dt - batch.time).total_seconds() / TRACK_SECONDS
    ra_step = (batch.ra[:, 1] - batch.ra[:, 0] + 540.0) % 360.0 - 180.0
    dec_step = batch.dec[:, 1] - batch.dec[:, 0]
    ra = (batch.ra[:, 0] + ra_step * part) % 360.0
    dec = batch.dec[:, 0] + dec_step * part
    alt = batch.alt[:, 0] + (batch.alt[:, 1] - batch.alt[:, 0]) * part
    with np.errstate(invalid="ignore"):
        keep = (
            (alt > 0)
            & (batch.mag <= mag_limit)
            & (angular_sep_deg(center[0], center[1], ra, dec) <= radius)
        )
    result = []
    # The batch is in brightness order.
    for i in np.flatnonzero(keep).tolist():
        obj = batch.objects[i]
        if obj.sequence in exclude:
            continue
        ahead_dec = float(dec[i] + dec_step[i])
        result.append(
            FieldSatellite(
                obj=obj,
                ra=float(ra[i]),
                dec=float(dec[i]),
                ahead_ra=float((ra[i] + ra_step[i]) % 360.0),
                ahead_dec=max(-90.0, min(90.0, ahead_dec)),
                mag=float(batch.mag[i]),
            )
        )
        if len(result) >= FIELD_CAP:
            break
    return result


def track_segment(
    x: float,
    y: float,
    ahead_x: float,
    ahead_y: float,
    gap: float,
    min_length: float,
    max_length: float,
) -> Optional[tuple[float, float, float, float]]:
    """The track line of a satellite at (x, y) on the screen.

    The line starts ``gap`` pixels from the satellite in the direction of
    (ahead_x, ahead_y), the position TRACK_SECONDS later. Its length is the
    distance to that position, limited to ``min_length`` and
    ``max_length``, so a slow satellite still shows its direction and a fast
    one does not cross the screen. None when the satellite moves less than
    half a pixel.
    """
    dx = ahead_x - x
    dy = ahead_y - y
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length < 0.5:
        return None
    ux, uy = dx / length, dy / length
    drawn = max(min_length, min(max_length, length))
    return (
        x + ux * gap,
        y + uy * gap,
        x + ux * (gap + drawn),
        y + uy * (gap + drawn),
    )
