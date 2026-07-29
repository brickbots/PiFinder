"""Dynamic catalog of MPC's bright asteroids for the observing year."""

from __future__ import annotations

import datetime
import logging
import threading
from pathlib import Path
from typing import Optional

import pytz

import PiFinder.asteroids as asteroids
from PiFinder import timez
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
from PiFinder.utils import Timer, asteroid_data_dir


logger = logging.getLogger("AsteroidCatalog")


class AsteroidCatalog(Catalog):
    POSITION_UPDATE_SECONDS = 601
    WAITING_FOR_DATA_SECONDS = 10

    def __init__(
        self,
        dt: datetime.datetime,
        shared_state: SharedStateObj,
        data_directory: Path = asteroid_data_dir,
    ):
        self._timer = TimerMixin()
        self._virtual_id_manager = VirtualIDManager()
        super().__init__("MP", "Asteroids")
        self.shared_state = shared_state
        self.data_directory = data_directory
        self._task_lock = threading.Lock()
        self._download_lock = threading.Lock()
        self.download_progress: Optional[int] = None
        self.calculation_progress: Optional[int] = None
        self._is_downloading = False
        self._cached_file_mtime: Optional[float] = None
        self._last_state = CatalogState.READY
        self.initialized = False

        self._timer.do_timed_task = self.do_timed_task
        self._timer.time_delay_seconds = lambda: self.time_delay_seconds

        if self.shared_state.altaz_ready() and self._element_files(dt):
            self.do_timed_task()
        threading.Thread(target=self._refresh_sources, daemon=True).start()
        self._timer.start_timer()
        self._start_background_retry()

    def _element_files(self, dt: datetime.datetime) -> list[Path]:
        return asteroids.available_element_files(dt, self.data_directory)

    @property
    def time_delay_seconds(self) -> int:
        return (
            self.POSITION_UPDATE_SECONDS
            if self.initialized
            else self.WAITING_FOR_DATA_SECONDS
        )

    def get_age(self) -> Optional[int]:
        if not self.shared_state.altaz_ready():
            return None
        files = self._element_files(self.shared_state.datetime())
        if not files:
            return None
        newest_mtime = max(path.stat().st_mtime for path in files)
        self._cached_file_mtime = newest_mtime
        local_date = timez.utc_from_timestamp(newest_mtime)
        now = self.shared_state.datetime()
        if now.tzinfo is None:
            now = pytz.UTC.localize(now)
        return round((now - local_date).total_seconds() / 86400.0)

    def get_data_label(self) -> Optional[str]:
        """Annual MPC sets are editions, not feeds that become stale daily."""
        dt = self.shared_state.datetime()
        if dt is not None:
            current = asteroids.asteroid_file_for_year(dt.year, self.data_directory)
            edition_year = dt.year if current.exists() else dt.year - 1
            return f"MPC {edition_year}"

        # A Pi 4 has no RTC, so its wall clock is not trustworthy before GPS.
        # Report only an edition that is proven by an on-disk filename.
        years = []
        for path in self.data_directory.glob("Soft00Bright-*.txt"):
            try:
                years.append(int(path.stem.rsplit("-", 1)[1]))
            except (IndexError, ValueError):
                continue
        return f"MPC {max(years)}" if years else None

    def get_status(self) -> CatalogStatus:
        if self._is_downloading:
            current = CatalogState.DOWNLOADING
        elif not self.shared_state.altaz_ready():
            current = CatalogState.NO_GPS
        elif self.calculation_progress is not None or not self.initialized:
            current = CatalogState.CALCULATING
        else:
            current = CatalogState.READY
        data = None
        if current == CatalogState.DOWNLOADING:
            data = {"progress": self.download_progress}
        elif (
            current == CatalogState.CALCULATING
            and self.calculation_progress is not None
        ):
            data = {"progress": self.calculation_progress}
        status = CatalogStatus(current, self._last_state, data)
        self._last_state = current
        return status

    def _download_year(self, year: int) -> bool:
        if not self._download_lock.acquire(blocking=False):
            return False
        try:
            self._is_downloading = True
            self.download_progress = 0

            def progress(value: Optional[int]) -> None:
                self.download_progress = value

            result = asteroids.download_asteroid_year(
                year, self.data_directory, progress_callback=progress
            )
            if result.success:
                self._cached_file_mtime = result.file_mtime
            return result.success
        finally:
            self._is_downloading = False
            self.download_progress = None
            self._download_lock.release()

    def _refresh_sources(self, force_recalculate: bool = False) -> None:
        if not self.shared_state.altaz_ready():
            logger.info("Deferring asteroid source selection until GPS time is ready")
            return
        dt = self.shared_state.datetime()
        if dt is None:
            return
        changed = False
        # Current year is required. If MPC has not published it yet, fetch the
        # previous year as an explicitly stale New-Year fallback. Next year is
        # opportunistic; a 404 leaves all active data untouched.
        for year in (dt.year,):
            needed, reason = asteroids.check_asteroid_download_needed(
                year, self.data_directory
            )
            if needed:
                logger.info("Asteroid data %s: %s", year, reason)
                changed = self._download_year(year) or changed
        if not asteroids.asteroid_file_for_year(dt.year, self.data_directory).exists():
            previous_year = dt.year - 1
            needed, reason = asteroids.check_asteroid_download_needed(
                previous_year, self.data_directory
            )
            if needed:
                logger.info("Asteroid fallback data %s: %s", previous_year, reason)
                changed = self._download_year(previous_year) or changed

        next_year = dt.year + 1
        needed, reason = asteroids.check_asteroid_download_needed(
            next_year, self.data_directory
        )
        if needed:
            logger.info("Asteroid next-year data %s: %s", next_year, reason)
            changed = self._download_year(next_year) or changed
        if (changed or force_recalculate) and self.shared_state.altaz_ready():
            self.do_timed_task()

    def refresh(self) -> None:
        threading.Thread(
            target=self._refresh_sources,
            kwargs={"force_recalculate": True},
            daemon=True,
        ).start()

    def _start_background_retry(self) -> None:
        def retry() -> None:
            retry_wait = threading.Event()
            while True:
                if not self.shared_state.altaz_ready():
                    retry_wait.wait(self.WAITING_FOR_DATA_SECONDS)
                    continue
                dt = self.shared_state.datetime()
                if dt is None:
                    retry_wait.wait(self.WAITING_FOR_DATA_SECONDS)
                    continue
                if self._element_files(dt):
                    break
                self._refresh_sources()
                if self._element_files(dt):
                    break
                retry_wait.wait(60)

        threading.Thread(target=retry, daemon=True).start()

    def _make_object(self, asteroid: dict) -> CompositeObject:
        ra, dec = asteroid["radec"]
        mag = MagnitudeObject([asteroid["mag"]])
        opposition_kind = asteroid.get("opposition_kind", "Opposition")
        opposition_date = asteroid.get("opposition_date")
        peak_date = asteroid.get("peak_date")
        description_lines = []
        if opposition_date:
            event_label = "Opp" if opposition_kind == "Opposition" else "Elong"
            description_lines.append(f"{event_label}: {opposition_date.isoformat()}")
        else:
            description_lines.append("Opp: unavailable")
        if peak_date:
            description_lines.append(
                f"Peak {asteroid['peak_magnitude']:.1f}: {peak_date.isoformat()}"
            )
        description_lines.extend(
            (
                f"Earth: {asteroid['earth_distance']:.2f} AU",
                f"Sun: {asteroid['sun_distance']:.2f} AU",
                f"Motion: {asteroid['angular_motion_arcsec_per_hour']:.1f}\"/h",
            )
        )
        description = "\n".join(description_lines)
        return CompositeObject.from_dict(
            {
                "id": -1,
                "obj_type": "AS",
                "ra": ra,
                "dec": dec,
                "const": sf_utils.radec_to_constellation(ra, dec),
                "size": SizeObject([]),
                "mag": mag,
                "mag_str": mag.calc_two_mag_representation(),
                "names": [asteroid["name"]],
                "catalog_code": "MP",
                "sequence": asteroid["number"],
                "description": description,
                "earth_distance_au": asteroid["earth_distance"],
                "sun_distance_au": asteroid["sun_distance"],
                "angular_motion_arcsec_per_hour": asteroid[
                    "angular_motion_arcsec_per_hour"
                ],
                "opposition_date": opposition_date,
                "opposition_kind": opposition_kind,
                "peak_magnitude": asteroid.get("peak_magnitude"),
                "peak_date": peak_date,
            }
        )

    def init_asteroids(self, dt: datetime.datetime) -> None:
        self.calculation_progress = 0

        def progress(value: int) -> None:
            self.calculation_progress = value

        calculated = asteroids.calc_asteroids(
            dt, self._element_files(dt), progress_callback=progress
        )
        if not calculated:
            self.initialized = bool(self.get_objects())
            self.calculation_progress = None
            return
        objects = [self._make_object(item) for item in calculated.values()]
        self.replace_objects(objects)
        self._virtual_id_manager.mint_ids(self)
        if self.catalog_filter is not None:
            self.catalog_filter.mark_catalog_content_dirty()
        self.initialized = True
        self.calculation_progress = None

    def do_timed_task(self) -> None:
        with self._task_lock:
            with Timer("Asteroid Catalog periodic update"):
                if not self.shared_state.altaz_ready():
                    return
                dt = self.shared_state.datetime()
                if self._element_files(dt):
                    self.init_asteroids(dt)
