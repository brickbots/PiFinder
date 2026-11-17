"""Dynamic catalog of bright artificial satellites.

Satellites move up to one degree per second. The catalog updates the
positions of its objects in place every few seconds. It tells the lists to
build again only when their content can change: the set of objects, a filter
verdict, the set of satellites above the horizon, or the passes. The object
details screen asks ``live_radec`` for a position on every frame. Pass
predictions run in a separate thread, because they take many seconds on a Pi.

The catalog works only while satellites are in use. Each use calls
``touch``: the object list of the catalog, the object details screen of a
satellite, ``active_catalog``, ``tracked`` and ``live_radec``. Ten minutes
after the last use, the position updates, the pass predictions and the
downloads stop. The objects stay in the catalog with their last positions.
The next use updates the positions at once and starts the work again.

The shared state is a proxy to another process, so each call to it is slow.
One update reads the time and the location once.

A group whose download failed does not stop the catalog: the catalog uses
each selected group that has a file. The automatic download of a failed
group waits longer after each failure (see
``satellites.FAILED_RETRY_SECONDS``). When the catalog has no objects,
``get_status`` tells why: no group is selected, a download failed, or no
data came yet.
"""

from __future__ import annotations

import datetime
import logging
import math
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pytz
from skyfield.api import wgs84

import PiFinder.satellites as satellites
from PiFinder.calc_utils import sf_utils
from PiFinder.catalog_base import CatalogState, CatalogStatus
from PiFinder.catalogs import Catalog, ObjectLabel
from PiFinder.composite_object import CompositeObject, MagnitudeObject
from PiFinder.observing_nights import zone_for
from PiFinder.state import SharedStateObj
from PiFinder.utils import Timer, satellite_data_dir


logger = logging.getLogger("SatelliteCatalog")

CATALOG_CODE = satellites.CATALOG_CODE
OBJ_TYPE = satellites.OBJ_TYPE

# The mark before the start time of the next pass in the object list. It is
# the Nerd Font up arrow (UIModule._UP_ARROW): the device fonts have no U+2191.
RISE_MARK = "\ueb71"

# The registry of the catalog that the process uses. The object details
# screen and the mount control find the satellite of an object through it.
_active_catalog: Optional["SatelliteCatalog"] = None


def active_catalog() -> Optional["SatelliteCatalog"]:
    catalog = _active_catalog
    if catalog is not None:
        catalog.touch()
    return catalog


def is_satellite(obj) -> bool:
    return getattr(obj, "catalog_code", None) == CATALOG_CODE


def live_radec(obj, dt: datetime.datetime) -> Optional[tuple[float, float]]:
    """The J2000 RA/Dec of a satellite object at ``dt``, or None."""
    catalog = _active_catalog
    if catalog is None or not is_satellite(obj):
        return None
    return catalog.radec_of(obj.sequence, dt)


class SatelliteCatalog(Catalog):
    POSITION_UPDATE_SECONDS = 5
    WAITING_FOR_DATA_SECONDS = 10
    # The wait before the next check of the file ages.
    DOWNLOAD_RETRY_SECONDS = 60 * 60
    # The wait after an error in the download thread.
    DOWNLOAD_FAILED_RETRY_SECONDS = 60
    # The shortest wait between two checks of the download thread.
    MIN_DOWNLOAD_WAIT_SECONDS = 30
    # The reason of an empty catalog is read again after this time.
    EMPTY_REASON_SECONDS = 1.0
    # The catalog stops its work this long after the last use.
    IDLE_SECONDS = 10 * 60
    # sky_state uses the positions of the last update up to this age. The
    # update thread makes them each POSITION_UPDATE_SECONDS, plus its run
    # time.
    SKY_STATE_MAX_AGE_SECONDS = 2 * POSITION_UPDATE_SECONDS

    def __init__(
        self,
        shared_state: SharedStateObj,
        data_directory: Path = satellite_data_dir,
        start_threads: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ):
        global _active_catalog
        super().__init__(CATALOG_CODE, "Satellites")
        self.shared_state = shared_state
        self.data_directory = data_directory
        self._task_lock = threading.Lock()
        self._is_downloading = False
        self.download_progress: Optional[int] = None
        self._last_state = CatalogState.READY
        self._file_mtimes: dict[str, float] = {}
        self._tracked: dict[int, satellites.TrackedSatellite] = {}
        self._passes: dict[int, list[satellites.SatPass]] = {}
        self._pass_time: Optional[datetime.datetime] = None
        # The time and place of the newest pass request.
        self._pass_basis: Optional[tuple[datetime.datetime, float, float]] = None
        self._pass_lock = threading.Lock()
        self._pass_request: Optional[tuple] = None
        self._pass_running = False
        self._topos_cache: Optional[tuple[tuple, object]] = None
        # The positions of all satellites at one time, as arrays. See
        # sky_state.
        self._sky: Optional[satellites.SkyState] = None
        # The SGP4 models of _tracked for sky_state: (tracked, sats, array).
        self._sky_models: Optional[tuple[dict, list, object]] = None
        # The time zone of the location at the last position update.
        self._zone: datetime.tzinfo = pytz.utc
        # What the lists showed after the last update. See _list_signature.
        self._list_state: Optional[tuple] = None
        self.initialized = False
        # Use and work state. See touch and in_use.
        self._clock = clock
        self._use_lock = threading.Lock()
        self._last_use: Optional[float] = None
        self._active = False
        self._last_update: Optional[float] = None
        self._update_wake = threading.Event()
        self._download_wake = threading.Event()
        self._next_download_check: Optional[float] = None
        self._empty_reason_cache: Optional[tuple[float, dict]] = None
        # Called with the GroupRefresh of a download that the user asked for.
        self.on_refresh_done: Optional[Callable[[satellites.GroupRefresh], None]] = None
        _active_catalog = self

        if start_threads:
            threading.Thread(target=self._update_loop, daemon=True).start()
            threading.Thread(target=self._download_loop, daemon=True).start()

    # -- use ------------------------------------------------------------------

    def in_use(self) -> bool:
        """True when the last use is less than IDLE_SECONDS ago."""
        last = self._last_use
        return last is not None and self._clock() - last <= self.IDLE_SECONDS

    def touch(self) -> None:
        """Record a use of the catalog. The first use after an idle time
        starts the work again."""
        with self._use_lock:
            self._last_use = self._clock()
            if self._active:
                return
            self._active = True
        self._wake()

    def _wake(self) -> None:
        """Update the positions at once when that is fast: the objects exist
        and the element files did not change. Otherwise the update thread
        builds the objects again in the background."""
        logger.info("Satellite catalog in use: work starts")
        if self.initialized and not self._files_changed(record=False):
            try:
                self.do_timed_task()
            except Exception:  # a failed update must not stop the caller
                logger.exception("Satellite position update failed")
        self._update_wake.set()
        self._download_wake.set()

    def _update_step(self) -> Optional[float]:
        """One step of the update thread.

        Returns the seconds until the next step, or None when the catalog is
        idle. An idle catalog does no work until the next touch.
        """
        with self._use_lock:
            if not self.in_use():
                if self._active:
                    logger.info("Satellite catalog idle: work stops")
                self._active = False
                self._update_wake.clear()
                return None
        delay = self.time_delay_seconds
        last = self._last_update
        if self.initialized and last is not None:
            remaining = delay - (self._clock() - last)
            if remaining > 0:
                return remaining
        try:
            self.do_timed_task()
        except Exception:  # the thread must stay usable for the next step
            logger.exception("Satellite position update failed")
        return self.time_delay_seconds

    def _update_loop(self) -> None:
        while True:
            delay = self._update_step()
            if delay is None:
                self._update_wake.wait()
            else:
                time.sleep(delay)

    # -- data -----------------------------------------------------------------

    def _download_missing(self) -> None:
        """Download each selected group that has no file, so the first use
        has data."""
        missing = tuple(
            group
            for group in satellites.selected_groups(self.data_directory)
            if not satellites.group_file(group, self.data_directory).exists()
        )
        if missing:
            self._refresh_sources(groups=missing)

    def _download_step(self) -> Optional[float]:
        """One step of the download thread.

        While the catalog is in use, the file ages decide on a download, once
        each DOWNLOAD_RETRY_SECONDS. Returns the seconds until the next step,
        or None when the catalog is idle.
        """
        if not self.in_use():
            return None
        due = self._next_download_check
        if due is None or self._clock() >= due:
            result = self._refresh_sources()
            due = self._clock() + self._download_wait_seconds(result)
            self._next_download_check = due
        return max(1.0, due - self._clock())

    def _download_loop(self) -> None:
        try:
            self._download_missing()
        except Exception:  # the thread must stay usable for later downloads
            logger.exception("Satellite download failed")
        while True:
            try:
                timeout = self._download_step()
            except Exception:  # the thread must stay usable for later downloads
                logger.exception("Satellite download failed")
                timeout = self.DOWNLOAD_FAILED_RETRY_SECONDS
            self._download_wake.wait(timeout)
            self._download_wake.clear()

    def _download_wait_seconds(self, result: satellites.GroupRefresh) -> float:
        """The wait until the next check: DOWNLOAD_RETRY_SECONDS, or less
        when the retry time of a failed group comes first."""
        now = time.time()
        status = satellites.load_download_status(self.data_directory)
        wait = float(self.DOWNLOAD_RETRY_SECONDS)
        for group in satellites.selected_groups(self.data_directory):
            entry = status.get(group)
            if (
                entry is not None
                and entry.result == satellites.RESULT_FAILED
                and entry.next_retry is not None
            ):
                wait = min(wait, entry.next_retry - now)
        return max(float(self.MIN_DOWNLOAD_WAIT_SECONDS), wait)

    def _refresh_sources(
        self, force: bool = False, groups: Optional[tuple[str, ...]] = None
    ) -> satellites.GroupRefresh:
        started = []

        def on_start() -> None:
            started.append(True)
            self._is_downloading = True

        # The file times come from the system clock, so the age check uses
        # the system clock too.
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            result = satellites.refresh_groups(
                now,
                force,
                self.data_directory,
                progress_callback=self._set_download_progress,
                on_start=on_start,
                groups=groups,
            )
        finally:
            if started:
                self._is_downloading = False
                self.download_progress = None
        logger.info("Satellite download: %s %s", result.status, result.failed)
        return result

    def _set_download_progress(self, value: Optional[int]) -> None:
        self.download_progress = value

    def refresh(self) -> Optional[int]:
        """Start a download of the selected groups in the background.

        Returns None when the download starts. Returns the seconds to wait
        when the last download of each selected group is too recent.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        waits = satellites.forced_download_wait(now, self.data_directory)
        wait = min(waits.values(), default=0.0)
        if wait > 0:
            logger.info("Satellite refresh refused: wait %.0f s", wait)
            return math.ceil(wait)
        threading.Thread(target=self._user_refresh, daemon=True).start()
        return None

    def _user_refresh(self) -> None:
        """The forced download of ``refresh``. The result goes to
        ``on_refresh_done``, so the user sees it on any screen."""
        try:
            result = self._refresh_sources(force=True)
        except Exception:  # the user gets a message, not a dead thread
            logger.exception("Satellite download failed")
            result = satellites.GroupRefresh("failed")
        listener = self.on_refresh_done
        if listener is not None:
            listener(result)

    def _element_files(self) -> list[Path]:
        return [
            path
            for path in satellites.element_files(self.data_directory)
            if path.exists()
        ]

    def _files_changed(self, record: bool = True) -> bool:
        """True when the element files changed since the last update. With
        ``record``, the file times of now count as the last update."""
        mtimes = {str(path): path.stat().st_mtime for path in self._element_files()}
        if mtimes == self._file_mtimes:
            return False
        if record:
            self._file_mtimes = mtimes
        return True

    # -- status ---------------------------------------------------------------

    @property
    def time_delay_seconds(self) -> int:
        return (
            self.POSITION_UPDATE_SECONDS
            if self.initialized
            else self.WAITING_FOR_DATA_SECONDS
        )

    def get_age(self) -> Optional[int]:
        files = self._element_files()
        if not files or not self.shared_state.altaz_ready():
            return None
        newest = max(path.stat().st_mtime for path in files)
        now = self.shared_state.datetime()
        if now.tzinfo is None:
            now = pytz.UTC.localize(now)
        return round((now.timestamp() - newest) / 86400.0)

    def get_data_label(self) -> Optional[str]:
        return None

    # -- labels ---------------------------------------------------------------

    def label_options(self) -> list[ObjectLabel]:
        """The left column of the satellite list: the name (the default),
        the NORAD number or the COSPAR id."""
        return [
            ObjectLabel("name", "Name", name_label),
            ObjectLabel("norad", "NORAD", norad_label),
            ObjectLabel("cospar", "COSPAR", self.cospar_label),
        ]

    # The longest list_info_text: "90° NW", or RISE_MARK and "21:43".
    list_info_chars = 6

    def list_info_text(self, obj: CompositeObject) -> Optional[str]:
        """The INFO-mode text of a satellite in the object list.

        Above the horizon: the altitude and the compass direction, for
        example "42° SE". Below the horizon: the local start time of the
        next visible pass, for example RISE_MARK + "21:43", or "--" without
        one. The values come from the last position update.
        """
        if obj.alt is None or obj.az is None:
            return "--"
        if obj.alt > 0:
            return f"{obj.alt:.0f}° {satellites.compass(obj.az)}"
        if obj.next_pass_ts is None or obj.next_pass_ts < 0:
            return "--"
        start = datetime.datetime.fromtimestamp(obj.next_pass_ts, self._zone)
        return f"{RISE_MARK}{start.strftime('%H:%M')}"

    def cospar_label(self, obj: CompositeObject) -> str:
        """The COSPAR id of a satellite object, for example "1998-067A".
        A satellite without one gives its NORAD number."""
        sat = self._tracked.get(obj.sequence)
        cospar = sat.elements.cospar_id if sat is not None else ""
        return cospar or norad_label(obj)

    def get_status(self) -> CatalogStatus:
        """The state of the catalog.

        A catalog with objects is READY (or NO_GPS), and ``data["total"]``
        holds the number of objects. An empty catalog is DOWNLOADING,
        NO_GPS, CALCULATING (not built yet) or ERROR. An ERROR has
        ``data["reason"]``: "no_groups", "failed" (``data["groups"]`` holds
        the failed groups), "no_data" (a selected group has no file yet) or
        "too_old" (each element set is too old).
        """
        total = len(self._tracked)
        data: Optional[dict] = None
        if total:
            if self.shared_state.altaz_ready():
                current = CatalogState.READY
            else:
                current = CatalogState.NO_GPS
            data = {"total": total}
        elif self._is_downloading:
            current = CatalogState.DOWNLOADING
            data = {"progress": self.download_progress}
        elif not self.shared_state.altaz_ready():
            current = CatalogState.NO_GPS
        elif not self.initialized:
            current = CatalogState.CALCULATING
        else:
            data = self._empty_reason()
            if data.get("reason") == "downloading":
                current = CatalogState.DOWNLOADING
                data = {"progress": None}
            else:
                current = CatalogState.ERROR
        status = CatalogStatus(current, self._last_state, data)
        self._last_state = current
        return status

    def _empty_reason(self) -> dict:
        """Why the built catalog has no objects. The list asks on each
        frame, so the answer is kept for EMPTY_REASON_SECONDS."""
        now = self._clock()
        cache = self._empty_reason_cache
        if cache is not None and now - cache[0] < self.EMPTY_REASON_SECONDS:
            return cache[1]
        reason = satellites.catalog_empty_reason(self.data_directory)
        self._empty_reason_cache = (now, reason)
        return reason

    # -- positions ------------------------------------------------------------

    def _topos(self, location):
        """The Skyfield observer of ``location``, made once per place."""
        key = (location.lat, location.lon, location.altitude)
        cache = self._topos_cache
        if cache is None or cache[0] != key:
            cache = (key, wgs84.latlon(*key))
            self._topos_cache = cache
        return cache[1]

    def _last_topos(self):
        """The Skyfield observer of the last update, or None before it."""
        cache = self._topos_cache
        return None if cache is None else cache[1]

    def tracked(self, norad_id: int) -> Optional[satellites.TrackedSatellite]:
        """The satellite with its element set. A mount follow uses it.

        The elements do not age, so a satellite of an idle catalog is good.
        A catalog that has no objects yet builds them first.
        """
        self.touch()
        if not self.initialized:
            self.do_timed_task()
        return self._tracked.get(norad_id)

    def radec_of(
        self, norad_id: int, dt: datetime.datetime
    ) -> Optional[tuple[float, float]]:
        """The position at ``dt`` for the observer of the last update.

        The object details screen calls this many times per second, so it
        does not read the shared state.
        """
        self.touch()
        sat = self._tracked.get(norad_id)
        topos = self._last_topos()
        if sat is None or topos is None:
            return None
        return satellites.radec_at(sat, topos, dt)

    def sky_state(self, dt: datetime.datetime) -> Optional[satellites.SkyState]:
        """The positions and magnitudes of all satellites, as arrays, at a
        time at most SKY_STATE_MAX_AGE_SECONDS from ``dt``.

        The chart finds the satellites in its field with it. The state of
        the last position update serves when it is recent. Otherwise one
        vectorized SGP4 call makes a new state for the observer of the last
        update. This is not a use of the catalog: it does not call
        ``touch``. None when the catalog has no objects or no observer yet.
        """
        state = self._sky
        if state is not None and (
            abs((dt - state.time).total_seconds()) <= self.SKY_STATE_MAX_AGE_SECONDS
        ):
            return state
        tracked = self._tracked
        topos = self._last_topos()
        if not tracked or topos is None:
            return None
        models = self._sky_models
        if models is None or models[0] is not tracked:
            sats = list(tracked.values())
            models = (tracked, sats, satellites.satrec_array(sats))
            self._sky_models = models
        state = satellites.sky_state_many(models[1], topos, dt, models[2])
        self._sky = state
        return state

    def live_tracks(
        self, norad_ids: list[int], times: list[datetime.datetime]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """RA, Dec and altitude in degrees of the satellites ``norad_ids`` at
        ``times``, each as an (n, m) array, with one SGP4 call. A NORAD id
        that the catalog does not track gets NaN. Not a use of the catalog.
        """
        tracked = self._tracked
        topos = self._last_topos()
        shape = (len(norad_ids), len(times))
        ra = np.full(shape, np.nan)
        dec = np.full(shape, np.nan)
        alt = np.full(shape, np.nan)
        rows = [i for i, norad in enumerate(norad_ids) if norad in tracked]
        if not rows or topos is None:
            return ra, dec, alt
        sats = [tracked[norad_ids[i]] for i in rows]
        ra[rows], dec[rows], alt[rows] = satellites.sky_tracks(sats, topos, times)
        return ra, dec, alt

    def _next_visible(
        self, norad_id: int, dt: datetime.datetime
    ) -> Optional[satellites.SatPass]:
        for candidate in self._passes.get(norad_id, []):
            if candidate.visible and candidate.set > dt:
                return candidate
        return None

    def _describe(
        self,
        sat: satellites.TrackedSatellite,
        now: satellites.SatLook,
        next_pass: Optional[satellites.SatPass],
        zone: datetime.tzinfo = pytz.utc,
    ) -> str:
        lines = []
        if now.alt > 0:
            lines.append(
                f"Alt {now.alt:.0f}° Az {now.az:.0f}° {satellites.compass(now.az)}"
            )
            lines.append(f"Range {now.range_km:.0f} km")
            if now.mag is None:
                lines.append("In Earth shadow")
            elif now.sun_alt > satellites.DARK_SUN_ALT_DEG:
                lines.append(f"Mag {now.mag:.1f}, sky too bright")
            else:
                lines.append(f"Mag {now.mag:.1f}, visible")
        else:
            lines.append("Below horizon")
        if sat.elements.geostationary:
            lines.append(
                "Geostationary: fixed in the sky"
                if now.alt > 0
                else "Geostationary: never rises here"
            )
        elif next_pass is not None:
            start = next_pass.visible_start or next_pass.rise
            lines.append(
                f"Next: {start.astimezone(zone).strftime('%H:%M')} "
                f"{satellites.compass(next_pass.rise_az)}"
                f"->{satellites.compass(next_pass.set_az)} "
                f"max {next_pass.max_alt:.0f}°"
                + (
                    f" mag {next_pass.min_mag:.1f}"
                    if next_pass.min_mag is not None
                    else ""
                )
            )
        elif self._pass_time is not None:
            lines.append(f"No visible pass in {satellites.PASS_HOURS:.0f} h")
        else:
            lines.append("Passes: calculating")
        age = sat.elements.age_days(now.time)
        lines.append(f"NORAD {sat.norad_id}")
        cospar = sat.elements.cospar_id
        if cospar:
            lines.append(f"COSPAR {cospar}")
        lines.append(f"TLE {age:.1f} d old")
        if sat.elements.source == "user":
            lines.append("Source: web entry")
        return "\n".join(lines)

    def _list_magnitude(
        self,
        sat: satellites.TrackedSatellite,
        now: satellites.SatLook,
        next_pass: Optional[satellites.SatPass],
    ) -> float:
        """Visible now: the current magnitude. Otherwise the peak of the next
        visible pass, and without a pass the standard magnitude."""
        if now.visible and now.mag is not None:
            return now.mag
        if next_pass is not None and next_pass.min_mag is not None:
            return next_pass.min_mag
        return sat.std_mag

    def _update_object(
        self,
        obj: CompositeObject,
        sat: satellites.TrackedSatellite,
        now: satellites.SatLook,
        zone: datetime.tzinfo,
        const: Optional[str],
    ) -> None:
        if not (math.isfinite(now.ra) and math.isfinite(now.dec)):
            # SGP4 cannot propagate this element set to the current time.
            obj.description = "No position: the elements are not usable"
            obj.alt = obj.az = None
            return
        next_pass = self._next_visible(sat.norad_id, now.time)
        obj.ra, obj.dec = now.ra, now.dec
        obj.alt, obj.az = now.alt, now.az
        obj.const = const or ""
        mag = round(self._list_magnitude(sat, now, next_pass), 1)
        # Most magnitudes do not change between two updates.
        if obj.mag.mags != [mag]:
            obj.mag = MagnitudeObject([mag])
            obj.mag_str = obj.mag.calc_two_mag_representation()
        obj.description = self._describe(sat, now, next_pass, zone)
        obj.next_pass_ts = self._pass_sort_key(now, next_pass)

    @staticmethod
    def _pass_sort_key(
        now: satellites.SatLook, next_pass: Optional[satellites.SatPass]
    ) -> Optional[float]:
        """The key of the "Next pass" sort order of the object list.

        A satellite above the horizon gets its negative altitude. It sorts
        before each satellite that is down, and the highest is first. The
        others get the start time of the next visible pass.
        """
        if now.alt > 0:
            return -now.alt
        if next_pass is None:
            return None
        return (next_pass.visible_start or next_pass.rise).timestamp()

    def _update_objects(self, dt: datetime.datetime, location) -> frozenset:
        """Move each object to its position at ``dt``.

        Returns the NORAD ids of the satellites above the horizon.
        """
        pairs = [
            (obj, sat)
            for obj in self._get_objects()
            if (sat := self._tracked.get(obj.sequence)) is not None
        ]
        topos = self._topos(location)
        zone = zone_for(location.timezone)
        self._zone = zone
        state = satellites.sky_state_many([sat for _obj, sat in pairs], topos, dt)
        self._sky = state
        looks = state.looks()
        consts = _constellations(state.ra, state.dec)
        for (obj, sat), now, const in zip(pairs, looks, consts):
            self._update_object(obj, sat, now, zone, const)
        return frozenset(
            sat.norad_id for (_obj, sat), now in zip(pairs, looks) if now.alt > 0
        )

    def _rebuild(self, dt: datetime.datetime, location) -> frozenset:
        tracked = {
            sat.norad_id: sat
            for sat in satellites.load_tracked(dt, self.data_directory)
        }
        self._tracked = tracked
        self.replace_objects(
            [satellites.make_object(sat.norad_id, sat.name) for sat in tracked.values()]
        )
        up_now = self._update_objects(dt, location)
        logger.info("Satellite catalog has %d objects", len(tracked))
        self._start_pass_update(dt, location)
        return up_now

    # -- passes ---------------------------------------------------------------

    def _start_pass_update(self, dt: datetime.datetime, location) -> None:
        """Ask for a pass update. A request during a run causes one more run
        after it, with the time, the place and the satellites of that moment."""
        self._pass_basis = (dt, location.lat, location.lon)
        with self._pass_lock:
            self._pass_request = (dt, location)
            if self._pass_running:
                return
            self._pass_running = True
        self._spawn_pass_worker()

    def _spawn_pass_worker(self) -> None:
        threading.Thread(target=self._run_pass_updates, daemon=True).start()

    def _run_pass_updates(self) -> None:
        while True:
            with self._pass_lock:
                request = self._pass_request
                self._pass_request = None
                if request is None:
                    self._pass_running = False
                    return
            try:
                self._update_passes(*request)
            except Exception:  # the worker must stay usable for the next request
                logger.exception("Satellite pass prediction failed")

    def _update_passes(self, dt: datetime.datetime, location) -> None:
        with Timer("Satellite pass prediction"):
            found = satellites.predict_passes(
                self._tracked.values(), self._topos(location), dt
            )
            self._passes = {sat.norad_id: items for sat, items in found}
            self._pass_time = dt

    def _passes_stale(self, dt: datetime.datetime, location) -> bool:
        """True when the newest pass request is old or for another place.

        The request counts, not the result, so a run that takes longer than
        one update does not cause a new request on each update.
        """
        if self._pass_basis is None:
            return False
        return satellites.passes_stale(*self._pass_basis, dt, location)

    # -- update ---------------------------------------------------------------

    def _list_signature(self, up_now: frozenset) -> tuple:
        """What decides the content and the order of an object list.

        The filter verdict of each object, the satellites above the horizon
        and the time of the pass data. The lists build again only when this
        changes. Positions and magnitudes change in the objects on each
        update, and the lists read them from there.
        """
        verdicts = b""
        if self.catalog_filter is not None:
            verdicts = np.packbits(
                self.catalog_filter.verdicts(list(self._get_objects()))
            ).tobytes()
        return (verdicts, up_now, self._pass_time)

    def do_timed_task(self) -> None:
        with self._task_lock:
            if not self.shared_state.altaz_ready():
                return
            dt = self.shared_state.datetime()
            location = self.shared_state.location()
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            self._last_update = self._clock()
            if self._files_changed() or not self.initialized:
                # Without element files the catalog is built empty, and
                # get_status tells why.
                up_now = self._rebuild(dt, location)
                self.initialized = True
                self._list_state = None
            else:
                up_now = self._update_objects(dt, location)
                if self._passes_stale(dt, location):
                    self._start_pass_update(dt, location)
            state = self._list_signature(up_now)
            if state != self._list_state:
                self._list_state = state
                self.invalidate_filter_cache()
                if self.catalog_filter is not None:
                    self.catalog_filter.mark_catalog_content_dirty()


def name_label(obj: CompositeObject) -> str:
    """The name of a satellite object, for example "ISS (ZARYA)"."""
    return obj.names[0] if obj.names else norad_label(obj)


def norad_label(obj: CompositeObject) -> str:
    """The NORAD number of a satellite object, for example "25544"."""
    return str(obj.sequence)


def _constellations(ra: np.ndarray, dec: np.ndarray) -> list[Optional[str]]:
    """The constellation of each position, with one lookup for all.

    A position that is not finite gets None.
    """
    finite = np.isfinite(ra) & np.isfinite(dec)
    result: list[Optional[str]] = [None] * len(ra)
    if finite.any():
        names = sf_utils.radec_to_constellations(ra[finite], dec[finite])
        for index, name in zip(np.flatnonzero(finite).tolist(), names.tolist()):
            result[index] = name
    return result
