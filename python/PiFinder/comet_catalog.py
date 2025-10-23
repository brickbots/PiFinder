import logging
import os
import time
import datetime
import pytz
import threading
from typing import Dict, Optional, Tuple
from PiFinder.catalog_base import CatalogStatus, CatalogState, TimerMixin, VirtualIDManager
from PiFinder.catalogs import Catalog
from PiFinder.state import SharedStateObj
from PiFinder.composite_object import CompositeObject, MagnitudeObject
import PiFinder.comets as comets
from PiFinder.utils import Timer, comet_file
from PiFinder.calc_utils import sf_utils

logger = logging.getLogger("CometCatalog")


class CometCatalog(Catalog):
    """Creates a catalog of comets with adaptive update frequency based on GPS lock status

        Logic:
            - on startup, do init and dispatch a setup background task:
                - check if we have a file, if so which file modification time and store that time.
                - if we don't have a file, set want_download to true and log the reason
                - if we have a file, try to get the remote file header, if the file is too old set want_download to true and set the age and log the reason
            - start the background download task, but wait till it returns
            - manually start the do_timed_task so it starts immediately, use locks to prevent double start
    """

    def __init__(self, dt: datetime.datetime, shared_state: SharedStateObj):
        # Create timer BEFORE calling super().__init__ because Catalog sets initialized=True
        self._timer = TimerMixin()
        self._virtual_id_manager = VirtualIDManager()

        super().__init__("CM", "Comets")
        self.shared_state = shared_state
        self._task_lock = threading.Lock()
        self._download_lock = threading.Lock()
        self.download_progress: Optional[int] = None
        self.calculation_progress: Optional[int] = None
        self._is_downloading: bool = False
        self._cached_file_mtime: Optional[float] = None  # Cache file modification time
        self._last_state: CatalogState = CatalogState.READY

        # Override Catalog's initialized=True since we need to wait for GPS/calculation
        self.initialized = False

        # Configure timer after initialization
        self._timer.do_timed_task = self.do_timed_task
        self._timer.time_delay_seconds = lambda: self.time_delay_seconds

        # Check if we need to download
        want_download, reason = comets.check_if_comet_download_needed(comet_file)

        if want_download:
            logger.info(f"Download needed: {reason}")
            # Start download in background and wait for completion
            download_thread = threading.Thread(target=self._download_once, daemon=True)
            download_thread.start()
            download_thread.join()  # Wait for download to complete

        # Now try to initialize comets immediately (if GPS available)
        if self.shared_state.altaz_ready() and os.path.exists(comet_file):
            self.do_timed_task()  # Initialize immediately

        # Start timer after initialization
        self._timer.start_timer()

        # Start background retry loop (only retries if no file exists)
        self._start_background_retry()

    def get_age(self) -> Optional[int]:
        """Return the age of the comet data in days.
        Uses cached file modification time to avoid repeated SD card access."""

        # Need GPS time for accurate age
        if not self.shared_state.altaz_ready():
            return None  # Will show as "?"
        if not os.path.exists(comet_file):
            return None

        # Use cached mtime if available, otherwise read from disk
        if self._cached_file_mtime is None:
            self._cached_file_mtime = os.path.getmtime(comet_file)

        # Get file modification time from cache
        local_date = datetime.datetime.fromtimestamp(
            self._cached_file_mtime, tz=pytz.UTC
        )

        # Calculate age using GPS time
        now = self.shared_state.datetime()
        if now.tzinfo is None:
            now = now.replace(tzinfo=pytz.UTC)

        age_days = (now - local_date).total_seconds() / 86400
        return round(age_days)

    def get_status(self) -> CatalogStatus:
        """Return the current status of the comet catalog"""
        if self._is_downloading:
            current_state = CatalogState.DOWNLOADING
        elif not self.shared_state.altaz_ready():
            current_state = CatalogState.NO_GPS
        elif not self.initialized:
            current_state = CatalogState.CALCULATING
        else:
            current_state = CatalogState.READY

        # Include progress data if available
        data = None
        if current_state == CatalogState.DOWNLOADING and self.download_progress is not None:
            data = {"progress": self.download_progress}
        elif current_state == CatalogState.CALCULATING and self.calculation_progress is not None:
            data = {"progress": self.calculation_progress}

        status = CatalogStatus(
            current=current_state,
            previous=self._last_state,
            data=data
        )
        self._last_state = status.current
        return status

    def _download_once(self):
        """Download comet data once with progress tracking.
        Does not check if download is needed - just downloads."""

        if not self._download_lock.acquire(blocking=False):
            logger.debug("Download already in progress, skipping")
            return False

        try:
            def progress_callback(progress: int):
                self.download_progress = progress

            self._is_downloading = True
            self.download_progress = 0

            success, _, file_mtime = comets.comet_data_download(
                comet_file,
                progress_callback=progress_callback
            )
            self._is_downloading = False
            self.download_progress = None

            # Update cached mtime after download - use the timestamp from download
            if success and file_mtime is not None:
                self._cached_file_mtime = file_mtime

            age = self.get_age()
            age_str = f"{age} days" if age is not None else "? days"
            logger.info(f"Download completed: success={success}, age={age_str}")
            return success
        finally:
            self._download_lock.release()

    def refresh(self):
        """
        Trigger a refresh by checking if download is needed.
        Only deletes file if remote is newer.
        """
        logger.info("Refresh called - checking if download needed")

        # Clear existing objects immediately
        if self.get_objects():
            self._get_objects().clear()
            self.max_sequence = 0
            self.id_to_pos = {}
            self.sequence_to_pos = {}
        self.initialized = False

        # Do the check and download in background thread to return immediately
        def refresh_task():
            # Check if we need to download
            want_download, reason = comets.check_if_comet_download_needed(comet_file)

            if want_download:
                logger.info(f"Refresh will download: {reason}")
                # Delete file to trigger download
                if os.path.exists(comet_file):
                    os.remove(comet_file)
                    logger.info("Deleted comet file")

                # Download
                self._download_once()
            else:
                logger.info(f"Refresh using existing file: {reason}")
                # File is fresh, just reinitialize from existing file
                if self.shared_state.altaz_ready() and os.path.exists(comet_file):
                    self.do_timed_task()

        threading.Thread(target=refresh_task, daemon=True).start()

    def _start_background_retry(self):
        """
        Retry download in background if file doesn't exist.
        Only retries when download failed (no file exists).
        Does NOT check file age - that's done once at startup.
        """
        def retry_task():
            # Only retry if no file exists
            while not os.path.exists(comet_file):
                time.sleep(60)
                logger.info("Retrying download: no file exists")
                success = self._download_once()
                if success and os.path.exists(comet_file):
                    # Download succeeded, try to initialize
                    if self.shared_state.altaz_ready():
                        self.do_timed_task()
                    break

        threading.Thread(target=retry_task, daemon=True).start()

    @property
    def time_delay_seconds(self) -> int:
        if self.initialized:
            return 293
        else:
            # Check for GPS lock/time every 5 second when uninitialized
            return 5

    def init_comets(self, dt):
        """Initialize comet catalog - called when GPS lock is available. Idempotent."""
        logger.info("Starting comet calculation")
        # Clear any existing objects to make this idempotent
        if self.get_objects():
            self._get_objects().clear()
            self.max_sequence = 0
            self.id_to_pos = {}
            self.sequence_to_pos = {}

        def progress_callback(progress: int):
            self.calculation_progress = progress

        # Set progress to 0 immediately so UI shows it right away
        self.calculation_progress = 0
        comet_dict = comets.calc_comets(dt, progress_callback=progress_callback)

        if not comet_dict:
            self.initialized = False
            self.calculation_progress = None
            return

        for sequence, (name, comet) in enumerate(comet_dict.items()):
            self.add_comet(sequence, name, comet)

        with self._virtual_id_manager.virtual_id_lock:
            new_low = self._virtual_id_manager.assign_virtual_object_ids(
                self, self._virtual_id_manager.virtual_id_low
            )
            self._virtual_id_manager.virtual_id_low = new_low

        self.initialized = True
        self.calculation_progress = None  # Clear progress after completion

    def add_comet(self, sequence: int, name: str, comet: Dict[str, Dict[str, float]]):
        """Add a single comet to the catalog"""
        try:
            ra, dec = comet["radec"]
            constellation = sf_utils.radec_to_constellation(ra, dec)
            desc = f"Distance to\nEarth: {comet['earth_distance']:.2f} AU\nSun: {comet['sun_distance']:.2f} AU"

            mag = MagnitudeObject([comet.get("mag", [])])
            obj = CompositeObject.from_dict(
                {
                    "id": -1,
                    "obj_type": "CM",
                    "ra": ra,
                    "dec": dec,
                    "const": constellation,
                    "size": "",
                    "mag": mag,
                    "mag_str": mag.calc_two_mag_representation(),
                    "names": [name],
                    "catalog_code": "CM",
                    "sequence": sequence + 1,
                    "description": desc,
                }
            )
            self.add_object(obj)
        except (KeyError, ValueError) as e:
            logger.error(f"Error adding comet {name}: {e}")

    def do_timed_task(self):
        """Update comet catalog data periodically







        """
        # Prevent concurrent execution
        with self._task_lock:
            with Timer("Comet Catalog periodic update"):
                if not self.shared_state.altaz_ready():
                    return

                dt = self.shared_state.datetime()

                # If catalog is empty, (re)initialize - but only if file exists
                if not self.get_objects():
                    if os.path.exists(comet_file):
                        self.init_comets(dt)
                    return

                # Regular update - recalculate positions
                comet_dict = comets.calc_comets(dt)
                if not comet_dict:
                    return

                for obj in self._get_objects():
                    try:
                        name = obj.names[0]
                        if name in comet_dict:
                            comet = comet_dict[name]
                            obj.ra, obj.dec = comet["radec"]
                            obj.mag = MagnitudeObject([comet["mag"]])
                            obj.const = sf_utils.radec_to_constellation(obj.ra, obj.dec)
                            obj.mag_str = obj.mag.calc_two_mag_representation()
                    except (KeyError, ValueError) as e:
                        logger.error(f"Error updating comet {name}: {e}")
