"""Dynamic catalog of bright artificial satellites.

Satellites move up to one degree per second. The catalog updates the
positions of its objects in place every few seconds. It tells the lists to
build again only when their content can change: the set of objects, a filter
verdict, the set of satellites above the horizon, or the passes. The object
details screen asks ``live_radec`` for a position on every frame. Pass
predictions run in a separate thread, because they take many seconds on a Pi.

The shared state is a proxy to another process, so each call to it is slow.
One update reads the time and the location once.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import pytz

import PiFinder.satellites as satellites
from PiFinder.calc_utils import sf_utils
from PiFinder.catalog_base import (
    CatalogState,
    CatalogStatus,
    TimerMixin,
    VirtualIDManager,
)
from PiFinder.catalogs import Catalog
from PiFinder.composite_object import CompositeObject, MagnitudeObject, SizeObject
from PiFinder.state import SharedStateObj
from PiFinder.utils import Timer, satellite_data_dir


logger = logging.getLogger("SatelliteCatalog")

CATALOG_CODE = "SA"
OBJ_TYPE = "Sat"

# The registry of the catalog that the process uses. The object details
# screen and the mount control find the satellite of an object through it.
_active_catalog: Optional["SatelliteCatalog"] = None


def active_catalog() -> Optional["SatelliteCatalog"]:
    return _active_catalog


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
    PASS_UPDATE_SECONDS = 30 * 60
    PASS_HOURS = 24.0
    # The wait before the next check of the file ages.
    DOWNLOAD_RETRY_SECONDS = 60 * 60
    # The wait after a download that failed.
    DOWNLOAD_FAILED_RETRY_SECONDS = 60
    MIN_PASS_ALT_DEG = 10.0

    def __init__(
        self,
        shared_state: SharedStateObj,
        data_directory: Path = satellite_data_dir,
        start_threads: bool = True,
    ):
        global _active_catalog
        self._timer = TimerMixin()
        self._virtual_id_manager = VirtualIDManager()
        super().__init__(CATALOG_CODE, "Satellites")
        self.shared_state = shared_state
        self.data_directory = data_directory
        self._task_lock = threading.Lock()
        self._is_downloading = False
        self._download_failed = False
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
        # What the lists showed after the last update. See _list_signature.
        self._list_state: Optional[tuple] = None
        self.initialized = False
        _active_catalog = self

        self._timer.do_timed_task = self.do_timed_task
        self._timer.time_delay_seconds = lambda: self.time_delay_seconds
        if start_threads:
            threading.Thread(target=self._startup_task, daemon=True).start()

    # -- data -----------------------------------------------------------------

    def _startup_task(self) -> None:
        if self.shared_state.altaz_ready():
            self.do_timed_task()
        self._timer.start_timer()
        retry_wait = threading.Event()
        while True:
            retry_wait.wait(self._download_wait_seconds(self._refresh_sources()))

    def _download_wait_seconds(self, result: satellites.GroupRefresh) -> float:
        if result.status == "failed":
            return self.DOWNLOAD_FAILED_RETRY_SECONDS
        return self.DOWNLOAD_RETRY_SECONDS

    def _refresh_sources(self, force: bool = False) -> satellites.GroupRefresh:
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
            )
        finally:
            if started:
                self._is_downloading = False
                self.download_progress = None
        if started:
            self._download_failed = result.status == "failed"
        logger.info("Satellite download: %s %s", result.status, result.failed)
        return result

    def _set_download_progress(self, value: Optional[int]) -> None:
        self.download_progress = value

    def refresh(self) -> Optional[int]:
        """Start a download of the groups in the background.

        Returns None when the download starts. Returns the seconds to wait
        when the last download is too recent.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        wait = min(satellites.forced_download_wait(now, self.data_directory).values())
        if wait > 0:
            logger.info("Satellite refresh refused: wait %.0f s", wait)
            return math.ceil(wait)
        threading.Thread(
            target=self._refresh_sources, kwargs={"force": True}, daemon=True
        ).start()
        return None

    def _element_files(self) -> list[Path]:
        files = [
            satellites.group_file(group, self.data_directory)
            for group in satellites.CELESTRAK_GROUPS
        ]
        files.append(satellites.user_file(self.data_directory))
        files.append(satellites.user_mag_file(self.data_directory))
        files.append(satellites.selection_file(self.data_directory))
        return [path for path in files if path.exists()]

    def _files_changed(self) -> bool:
        mtimes = {str(path): path.stat().st_mtime for path in self._element_files()}
        if mtimes != self._file_mtimes:
            self._file_mtimes = mtimes
            return True
        return False

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

    def get_status(self) -> CatalogStatus:
        if self._is_downloading and not self._tracked:
            current = CatalogState.DOWNLOADING
        elif not self.shared_state.altaz_ready():
            current = CatalogState.NO_GPS
        elif self.initialized:
            current = CatalogState.READY
        elif self._download_failed and not self._element_files():
            current = CatalogState.ERROR
        else:
            current = CatalogState.CALCULATING
        data = None
        if current == CatalogState.DOWNLOADING:
            data = {"progress": self.download_progress}
        status = CatalogStatus(current, self._last_state, data)
        self._last_state = current
        return status

    # -- positions ------------------------------------------------------------

    def _topos(self, location):
        """The Skyfield observer of ``location``, made once per place."""
        key = (location.lat, location.lon, location.altitude)
        cache = self._topos_cache
        if cache is None or cache[0] != key:
            cache = (key, satellites.observer_topos(*key))
            self._topos_cache = cache
        return cache[1]

    def tracked(self, norad_id: int) -> Optional[satellites.TrackedSatellite]:
        return self._tracked.get(norad_id)

    def radec_of(
        self, norad_id: int, dt: datetime.datetime
    ) -> Optional[tuple[float, float]]:
        """The position at ``dt`` for the observer of the last update.

        The object details screen calls this many times per second, so it
        does not read the shared state.
        """
        sat = self._tracked.get(norad_id)
        cache = self._topos_cache
        if sat is None or cache is None:
            return None
        return satellites.radec_at(sat, cache[1], dt)

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
        if next_pass is not None:
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
            lines.append(f"No visible pass in {self.PASS_HOURS:.0f} h")
        else:
            lines.append("Passes: calculating")
        age = sat.elements.age_days(now.time)
        lines.append(f"NORAD {sat.norad_id}, TLE {age:.1f} d old")
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

    def _make_object(self, sat: satellites.TrackedSatellite) -> CompositeObject:
        return CompositeObject.from_dict(
            {
                "id": -1,
                "obj_type": OBJ_TYPE,
                "ra": 0.0,
                "dec": 0.0,
                "const": "",
                "size": SizeObject([]),
                "mag": MagnitudeObject([]),
                "mag_str": "-",
                "names": [sat.name],
                "catalog_code": CATALOG_CODE,
                "sequence": sat.norad_id,
                "description": "",
            }
        )

    def _update_object(
        self,
        obj: CompositeObject,
        sat: satellites.TrackedSatellite,
        now: satellites.SatLook,
        zone: datetime.tzinfo,
    ) -> None:
        if not (math.isfinite(now.ra) and math.isfinite(now.dec)):
            # SGP4 cannot propagate this element set to the current time.
            obj.description = "No position: the elements are not usable"
            return
        next_pass = self._next_visible(sat.norad_id, now.time)
        obj.ra, obj.dec = now.ra, now.dec
        obj.const = sf_utils.radec_to_constellation(now.ra, now.dec)
        obj.mag = MagnitudeObject([round(self._list_magnitude(sat, now, next_pass), 1)])
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
        zone = _zone(location.timezone)
        looks = satellites.look_many([sat for _obj, sat in pairs], topos, dt)
        for (obj, sat), now in zip(pairs, looks):
            self._update_object(obj, sat, now, zone)
        return frozenset(
            sat.norad_id for (_obj, sat), now in zip(pairs, looks) if now.alt > 0
        )

    def _rebuild(self, dt: datetime.datetime, location) -> frozenset:
        elements = satellites.load_all_elements(dt, self.data_directory)
        user_mags = satellites.load_user_mags(self.data_directory)
        tracked: dict[int, satellites.TrackedSatellite] = {}
        for element in elements:
            try:
                tracked[element.norad_id] = satellites.TrackedSatellite.from_elements(
                    element, user_mags
                )
            except ValueError as exc:
                logger.warning("Skipping %s: %s", element.name, exc)
        self._tracked = tracked
        self.replace_objects([self._make_object(sat) for sat in tracked.values()])
        up_now = self._update_objects(dt, location)
        self._virtual_id_manager.mint_ids(self)
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
            topos = satellites.observer_topos(
                location.lat, location.lon, location.altitude
            )
            start = dt - datetime.timedelta(minutes=15)
            tracked = list(self._tracked.values())
            passes: dict[int, list[satellites.SatPass]] = {}
            for sat in tracked:
                try:
                    passes[sat.norad_id] = satellites.find_passes(
                        sat, topos, start, self.PASS_HOURS, self.MIN_PASS_ALT_DEG
                    )
                except Exception as exc:  # one bad set must not stop the rest
                    logger.warning("No passes for %s: %s", sat.name, exc)
            self._passes = passes
            self._pass_time = dt
            self._write_pass_cache(dt, location, tracked, passes)

    def _write_pass_cache(
        self,
        dt: datetime.datetime,
        location,
        tracked: list[satellites.TrackedSatellite],
        passes: dict[int, list[satellites.SatPass]],
    ) -> None:
        """Write the passes for the web server, which runs in another process."""
        rows = []
        for sat in tracked:
            for item in passes.get(sat.norad_id, []):
                row = item.to_dict()
                row.update(norad_id=sat.norad_id, name=sat.name)
                rows.append(row)
        rows.sort(key=lambda row: row["rise"])
        cache = {
            "computed": dt.isoformat(),
            "hours": self.PASS_HOURS,
            "min_alt": self.MIN_PASS_ALT_DEG,
            "location": {"lat": location.lat, "lon": location.lon},
            "timezone": location.timezone or "UTC",
            "satellites": [
                {
                    "norad_id": sat.norad_id,
                    "name": sat.name,
                    "source": sat.elements.source,
                    "std_mag": sat.std_mag,
                    "epoch": sat.elements.epoch.isoformat(),
                }
                for sat in tracked
            ],
            "passes": rows,
        }
        path = satellites.pass_cache_file(self.data_directory)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(cache))
            temporary.replace(path)
        except OSError as exc:
            logger.warning("Cannot write %s: %s", path, exc)

    def _passes_stale(self, dt: datetime.datetime, location) -> bool:
        """True when the newest pass request is old or for another place.

        The request counts, not the result, so a run that takes longer than
        one update does not cause a new request on each update.
        """
        if self._pass_basis is None:
            return False
        requested, lat, lon = self._pass_basis
        moved = abs(lat - location.lat) > 0.5 or abs(lon - location.lon) > 0.5
        old = abs((dt - requested).total_seconds()) > self.PASS_UPDATE_SECONDS
        return moved or old

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
            if self._files_changed() or not self.initialized:
                if not self._element_files():
                    return
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


def _zone(name: Optional[str]) -> datetime.tzinfo:
    try:
        return pytz.timezone(name or "UTC")
    except pytz.exceptions.UnknownTimeZoneError:
        return pytz.utc
