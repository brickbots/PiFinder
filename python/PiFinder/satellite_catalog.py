"""Dynamic catalog of bright artificial satellites.

Satellites move up to one degree per second. The catalog updates the
positions of its objects in place every few seconds, so lists and filters
stay current. The object details screen asks ``live_radec`` for a position
on every frame. Pass predictions run in a separate thread, because they take
many seconds on a Pi.
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
from pathlib import Path
from typing import Optional

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
    DOWNLOAD_RETRY_SECONDS = 60 * 60
    MIN_PASS_ALT_DEG = 10.0

    def __init__(
        self,
        dt: datetime.datetime,
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
        self._pass_lock = threading.Lock()
        self._is_downloading = False
        self.download_progress: Optional[int] = None
        self._last_state = CatalogState.READY
        self._file_mtimes: dict[str, float] = {}
        self._tracked: dict[int, satellites.TrackedSatellite] = {}
        self._passes: dict[int, list[satellites.SatPass]] = {}
        self._pass_time: Optional[datetime.datetime] = None
        self._pass_location: Optional[tuple[float, float]] = None
        self._topos_cache: Optional[tuple[tuple, object]] = None
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
            self._refresh_sources()
            retry_wait.wait(self.DOWNLOAD_RETRY_SECONDS)

    def _refresh_sources(self, force: bool = False) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        for group in satellites.CELESTRAK_GROUPS:
            needed, reason = satellites.group_download_needed(
                group, now, self.data_directory
            )
            if not (needed or force):
                continue
            logger.info("Satellite group %s: %s", group, reason)
            self._is_downloading = True
            try:
                satellites.download_group(
                    group,
                    self.data_directory,
                    progress_callback=self._set_download_progress,
                )
            finally:
                self._is_downloading = False
                self.download_progress = None

    def _set_download_progress(self, value: Optional[int]) -> None:
        self.download_progress = value

    def refresh(self) -> None:
        threading.Thread(
            target=self._refresh_sources, kwargs={"force": True}, daemon=True
        ).start()

    def _element_files(self) -> list[Path]:
        files = [
            satellites.group_file(group, self.data_directory)
            for group in satellites.CELESTRAK_GROUPS
        ]
        files.append(satellites.user_file(self.data_directory))
        files.append(satellites.user_mag_file(self.data_directory))
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
        elif not self.initialized:
            current = CatalogState.CALCULATING
        else:
            current = CatalogState.READY
        data = None
        if current == CatalogState.DOWNLOADING:
            data = {"progress": self.download_progress}
        status = CatalogStatus(current, self._last_state, data)
        self._last_state = current
        return status

    # -- positions ------------------------------------------------------------

    def _topos(self):
        location = self.shared_state.location()
        key = (location.lat, location.lon, location.altitude)
        if self._topos_cache is None or self._topos_cache[0] != key:
            self._topos_cache = (key, satellites.observer_topos(*key))
        return self._topos_cache[1]

    def tracked(self, norad_id: int) -> Optional[satellites.TrackedSatellite]:
        return self._tracked.get(norad_id)

    def tracked_satellites(self) -> list[satellites.TrackedSatellite]:
        return list(self._tracked.values())

    def passes(self, norad_id: int) -> list[satellites.SatPass]:
        return list(self._passes.get(norad_id, []))

    def radec_of(
        self, norad_id: int, dt: datetime.datetime
    ) -> Optional[tuple[float, float]]:
        sat = self._tracked.get(norad_id)
        if sat is None or not self.shared_state.altaz_ready():
            return None
        return satellites.radec_at(sat, self._topos(), dt)

    def look(
        self, norad_id: int, dt: datetime.datetime
    ) -> Optional[satellites.SatLook]:
        sat = self._tracked.get(norad_id)
        if sat is None or not self.shared_state.altaz_ready():
            return None
        return satellites.look(sat, self._topos(), dt)

    def _local_time(self, dt: datetime.datetime) -> str:
        zone_name = self.shared_state.location().timezone or "UTC"
        try:
            zone = pytz.timezone(zone_name)
        except pytz.exceptions.UnknownTimeZoneError:
            zone = pytz.utc
        return dt.astimezone(zone).strftime("%H:%M")

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
    ) -> str:
        lines = []
        if now.alt > 0:
            lines.append(
                f"Now: alt {now.alt:.0f}° {satellites.compass(now.az)} "
                f"{now.range_km:.0f} km"
            )
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
                f"Next: {self._local_time(start)} "
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

    def _make_object(
        self,
        sat: satellites.TrackedSatellite,
        dt: datetime.datetime,
        sun: Optional[satellites.SunContext] = None,
    ) -> CompositeObject:
        obj = CompositeObject.from_dict(
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
        self._update_object(obj, sat, dt, sun)
        return obj

    def _update_object(
        self,
        obj: CompositeObject,
        sat: satellites.TrackedSatellite,
        dt: datetime.datetime,
        sun: Optional[satellites.SunContext] = None,
    ) -> None:
        now = satellites.look(sat, self._topos(), dt, with_rates=False, sun=sun)
        next_pass = self._next_visible(sat.norad_id, dt)
        obj.ra, obj.dec = now.ra, now.dec
        obj.const = sf_utils.radec_to_constellation(now.ra, now.dec)
        obj.mag = MagnitudeObject([round(self._list_magnitude(sat, now, next_pass), 1)])
        obj.mag_str = obj.mag.calc_two_mag_representation()
        obj.description = self._describe(sat, now, next_pass)
        obj.next_pass_ts = (
            (next_pass.visible_start or next_pass.rise).timestamp()
            if next_pass is not None
            else None
        )

    def _rebuild(self, dt: datetime.datetime) -> None:
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
        sun = satellites.sun_context(self._topos(), dt)
        objects = [self._make_object(sat, dt, sun) for sat in tracked.values()]
        self.replace_objects(objects)
        self._virtual_id_manager.mint_ids(self)
        logger.info("Satellite catalog has %d objects", len(objects))
        self._start_pass_update(dt)

    def _start_pass_update(self, dt: datetime.datetime) -> None:
        threading.Thread(target=self._update_passes, args=(dt,), daemon=True).start()

    def _update_passes(self, dt: datetime.datetime) -> None:
        if not self._pass_lock.acquire(blocking=False):
            return
        try:
            with Timer("Satellite pass prediction"):
                topos = self._topos()
                location = self.shared_state.location()
                start = dt - datetime.timedelta(minutes=15)
                passes: dict[int, list[satellites.SatPass]] = {}
                for sat in list(self._tracked.values()):
                    try:
                        passes[sat.norad_id] = satellites.find_passes(
                            sat, topos, start, self.PASS_HOURS, self.MIN_PASS_ALT_DEG
                        )
                    except Exception as exc:  # one bad set must not stop the rest
                        logger.warning("No passes for %s: %s", sat.name, exc)
                self._passes = passes
                self._pass_time = dt
                self._pass_location = (location.lat, location.lon)
                self._write_pass_cache(dt, location)
        finally:
            self._pass_lock.release()

    def _write_pass_cache(self, dt: datetime.datetime, location) -> None:
        """Write the passes for the web server, which runs in another process."""
        tracked = list(self._tracked.values())
        rows = []
        for sat in tracked:
            for item in self._passes.get(sat.norad_id, []):
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

    def _passes_stale(self, dt: datetime.datetime) -> bool:
        if self._pass_time is None:
            return False
        location = self.shared_state.location()
        moved = self._pass_location is not None and (
            abs(self._pass_location[0] - location.lat) > 0.5
            or abs(self._pass_location[1] - location.lon) > 0.5
        )
        old = (dt - self._pass_time).total_seconds() > self.PASS_UPDATE_SECONDS
        return moved or old

    def do_timed_task(self) -> None:
        with self._task_lock:
            if not self.shared_state.altaz_ready():
                return
            dt = self.shared_state.datetime()
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            if self._files_changed() or not self.initialized:
                if not self._element_files():
                    return
                self._rebuild(dt)
                self.initialized = True
            else:
                sun = satellites.sun_context(self._topos(), dt)
                for obj in self._get_objects():
                    sat = self._tracked.get(obj.sequence)
                    if sat is not None:
                        self._update_object(obj, sat, dt, sun)
                if self._passes_stale(dt):
                    self._start_pass_update(dt)
            self.invalidate_filter_cache()
            if self.catalog_filter is not None:
                self.catalog_filter.mark_catalog_content_dirty()
