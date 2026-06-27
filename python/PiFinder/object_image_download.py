#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
App-owned background **Download** worker for object images (ADR 0018).

A single ``ObjectImageDownloader`` lives for the life of the main UI process
(wired in ``main.py``) and is shared by the download UI screens and the global
title-bar status line.  It owns one background thread that fans a worklist of
sourceless ``image_name``s out over a small ``ThreadPoolExecutor`` (download is
I/O-bound, so the GIL is released on network/file I/O).

Lifecycle (handoff "Lifecycle: manual re-trigger, idempotent skip"):
  * One run at a time; ``start()`` is a no-op while a run is active.
  * ``cancel()`` (or BACK) stops scheduling new work and lets in-flight fetches
    finish; **already-downloaded files are kept** (each write is atomic).
  * No auto-resume — re-running a scope just skips files already present.

UI screens never touch the thread; they read an immutable :class:`DownloadProgress`
snapshot via :meth:`ObjectImageDownloader.progress` and call start / cancel.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional

from PiFinder import object_image_store as store

logger = logging.getLogger("Catalog.ImageDownload")

# Run states.
IDLE = "idle"
RUNNING = "running"
DONE = "done"
CANCELLED = "cancelled"
ERROR = "error"


@dataclass(frozen=True)
class DownloadProgress:
    """Immutable snapshot of a download run for the UI to visualize."""

    state: str
    total: int
    downloaded: int
    skipped: int
    missing: int
    errors: int

    @property
    def completed(self) -> int:
        """Images processed so far (downloaded + skipped + missing + errors)."""
        return self.downloaded + self.skipped + self.missing + self.errors

    @property
    def active(self) -> bool:
        return self.state == RUNNING

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        return min(100, int(100 * self.completed / self.total))


class ObjectImageDownloader:
    """Background controller for on-device object-image downloads."""

    def __init__(self, workers: int = store.DEFAULT_DOWNLOAD_WORKERS):
        self._workers = workers
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Guarded by ``_lock``.
        self._state = IDLE
        self._total = 0
        self._downloaded = 0
        self._skipped = 0
        self._missing = 0
        self._errors = 0

    # -- public API --------------------------------------------------------- #
    def is_active(self) -> bool:
        with self._lock:
            return self._state == RUNNING

    def progress(self) -> DownloadProgress:
        with self._lock:
            return DownloadProgress(
                state=self._state,
                total=self._total,
                downloaded=self._downloaded,
                skipped=self._skipped,
                missing=self._missing,
                errors=self._errors,
            )

    def start(self, image_names: List[str]) -> bool:
        """Begin downloading ``image_names`` in the background.

        Returns ``False`` (and does nothing) if a run is already active.
        """
        with self._lock:
            if self._state == RUNNING:
                return False
            self._cancel.clear()
            self._state = RUNNING
            self._total = len(image_names)
            self._downloaded = 0
            self._skipped = 0
            self._missing = 0
            self._errors = 0
            thread = threading.Thread(
                target=self._run,
                args=(list(image_names),),
                name="ObjectImageDownloader",
                daemon=True,
            )
            self._thread = thread
        thread.start()
        return True

    def cancel(self) -> None:
        """Request cancellation; keeps files already written."""
        self._cancel.set()

    # -- worker ------------------------------------------------------------- #
    def _tally(self, result: str) -> None:
        with self._lock:
            if result == store.RESULT_DOWNLOADED:
                self._downloaded += 1
            elif result == store.RESULT_SKIPPED:
                self._skipped += 1
            elif result == store.RESULT_MISSING:
                self._missing += 1
            else:
                self._errors += 1

    def _fetch(self, session, image_name: str) -> str:
        # Queued tasks short-circuit once cancellation is requested so the pool
        # drains promptly without cancelling files already in flight.
        if self._cancel.is_set():
            return store.RESULT_SKIPPED
        return store.download_object_image(session, image_name)

    def _run(self, image_names: List[str]) -> None:
        store.create_catalog_image_dirs()
        session = store.new_session()
        try:
            with ThreadPoolExecutor(max_workers=self._workers) as executor:
                futures = {
                    executor.submit(self._fetch, session, name): name
                    for name in image_names
                }
                for future in as_completed(futures):
                    try:
                        self._tally(future.result())
                    except Exception as exc:  # defensive: never kill the thread
                        logger.debug("download task failed: %s", exc)
                        self._tally(store.RESULT_ERROR)
                    if self._cancel.is_set():
                        # Stop waiting on the rest; queued tasks short-circuit.
                        break
        except Exception as exc:
            logger.error("Object-image download run failed: %s", exc)
            with self._lock:
                self._state = ERROR
            session.close()
            return
        finally:
            session.close()

        with self._lock:
            self._state = CANCELLED if self._cancel.is_set() else DONE
        logger.info(
            "Object-image download finished: %s (%d downloaded, %d skipped, "
            "%d missing, %d errors of %d)",
            self._state,
            self._downloaded,
            self._skipped,
            self._missing,
            self._errors,
            self._total,
        )
