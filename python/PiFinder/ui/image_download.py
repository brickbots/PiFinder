#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
On-device **Download** UI for object images (ADR 0018).

Replaces the old SSH / ``python -m PiFinder.get_images`` step with an on-device
flow under Tools ▸ Download Images.  A scope-picker submenu (menu_structure)
launches this screen with a ``scope`` in its item definition; the screen then:

  1. gates on WiFi **Client** mode (reusing the software-update pattern),
  2. runs a **pre-flight** — missing count, rough size estimate, and a quick CDN
     reachability check — in a background thread so the UI stays smooth,
  3. starts the app-owned :class:`ObjectImageDownloader` and visualizes its
     progress, and
  4. shows a final summary.

The worker is app-owned and survives navigation: pressing BACK while a download
runs leaves it going (the global title-bar status line keeps it visible); a
separate Cancel action stops it, keeping files already downloaded.
"""

import logging
import threading
import time
from typing import Any, List, Optional, TYPE_CHECKING

from PiFinder import utils
from PiFinder import object_image_store as store
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.ui.base import UIModule

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


logger = logging.getLogger("UIImageDownload")

# Screen phases.
PHASE_PREFLIGHT = "preflight"
PHASE_RUNNING = "running"
PHASE_DONE = "done"


def _format_size(num_bytes: int) -> str:
    """Human-facing size estimate (``~12 MB`` / ``~640 KB``)."""
    mb = num_bytes / 1_000_000
    if mb >= 1:
        return _("~{n} MB").format(n=round(mb))
    return _("~{n} KB").format(n=max(1, round(num_bytes / 1000)))


class UIImageDownload(UIModule):
    """Download object images from the CDN to local disk, for a chosen scope."""

    __title__ = "IMAGES"
    # This screen visualizes the run itself, so suppress the global title-bar
    # download status line while it is on top of the stack.
    _suppress_download_status = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._scope = self.item_definition.get("scope", store.SCOPE_ALL)
        self._catalog_code = self.item_definition.get("catalog_code")

        self.wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
        self._wifi_mode = ""

        self._phase = PHASE_PREFLIGHT
        self._preflight_started = False

        # Pre-flight results (written by the background thread, read in update()).
        self._lock = threading.Lock()
        self._preflight_ready = False
        self._preflight_error: Optional[str] = None
        self._total = 0
        self._missing_names: List[str] = []
        self._reachable = False

        self._objects: Optional[list] = None  # live objects for filter/list scopes
        self._option_select = "Download"  # "Download" | "Cancel"
        self._elipsis_count = 0
        self._final = None  # captured DownloadProgress when a run finishes

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def active(self):
        super().active()
        self._wifi_mode = self._read_wifi_mode()

        # If a download is already running (started from another scope), just
        # show its progress rather than a new pre-flight.
        if self.object_image_downloader and self.object_image_downloader.is_active():
            self._phase = PHASE_RUNNING
            return

        if not self._preflight_started and self._wifi_mode == "Client":
            self._preflight_started = True
            # Gather live objects on the UI thread for the filter / list scopes
            # (the background thread only touches the DB, disk and network).
            if self._scope == store.SCOPE_FILTER:
                self._objects = list(
                    self.catalogs.get_objects(only_selected=True, filtered=True)
                )
            elif self._scope == store.SCOPE_LIST:
                self._objects = list(self.ui_state.observing_list())
            threading.Thread(target=self._compute_preflight, daemon=True).start()

    def _read_wifi_mode(self) -> str:
        try:
            with open(self.wifi_txt, "r") as wfs:
                return wfs.read().strip()
        except OSError:
            return ""

    def _worklist(self, cursor) -> List[str]:
        if self._scope in (store.SCOPE_ALL, store.SCOPE_CATALOG):
            return store.worklist_for_scope(
                self._scope, cursor, catalog_code=self._catalog_code
            )
        return store.worklist_for_scope(self._scope, cursor, objects=self._objects)

    def _compute_preflight(self):
        """Background: build the worklist, count missing, probe the CDN."""
        try:
            db = ObjectsDatabase()
            _, cursor = db.get_conn_cursor()
            names = self._worklist(cursor)
            missing = store.missing_image_names(names)
            reachable = store.cdn_reachable()
            with self._lock:
                self._total = len(names)
                self._missing_names = missing
                self._reachable = reachable
                self._preflight_ready = True
        except Exception as exc:
            logger.error("Image-download pre-flight failed: %s", exc)
            with self._lock:
                self._preflight_error = str(exc)
                self._preflight_ready = True

    # ------------------------------------------------------------------ #
    # Drawing
    # ------------------------------------------------------------------ #
    def update(self, force=False):
        time.sleep(1 / 30)
        self.clear_screen()

        if self._phase == PHASE_RUNNING:
            # Leave the running view once the worker finishes.
            if (
                self.object_image_downloader
                and not self.object_image_downloader.is_active()
            ):
                self._final = self.object_image_downloader.progress()
                self._phase = PHASE_DONE
            else:
                self._draw_running()
                return self.screen_update()

        if self._phase == PHASE_DONE:
            self._draw_done()
            return self.screen_update()

        self._draw_preflight()
        return self.screen_update()

    def _scope_label(self) -> str:
        if self._scope == store.SCOPE_ALL:
            return _("All objects")
        if self._scope == store.SCOPE_CATALOG:
            return _("Catalog {code}").format(code=self._catalog_code or "?")
        if self._scope == store.SCOPE_FILTER:
            return _("Current filter")
        if self._scope == store.SCOPE_LIST:
            return _("Observing list")
        return str(self._scope)

    def _draw_preflight(self):
        y = self.display_class.titlebar_height + 2

        self.draw.text(
            (0, y),
            self._scope_label(),
            font=self.fonts.bold.font,
            fill=self.colors.get(192),
        )
        y += self.fonts.bold.height + 4

        if self._wifi_mode != "Client":
            self.draw.text(
                (0, y),
                _("WiFi must be"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (0, y + self.fonts.large.height),
                _("client mode"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return

        with self._lock:
            ready = self._preflight_ready
            error = self._preflight_error
            total = self._total
            missing = len(self._missing_names)
            reachable = self._reachable

        if not ready:
            self._elipsis_count = (self._elipsis_count + 1) % 40
            self.draw.text(
                (0, y),
                _("Checking{e}").format(e="." * int(self._elipsis_count / 10)),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return

        if error:
            self.draw.text(
                (0, y),
                _("Error"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return

        # Counts
        self.draw.text(
            (0, y),
            _("{n} of {t} missing").format(n=missing, t=total),
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )
        y += self.fonts.base.height + 2
        self.draw.text(
            (0, y),
            _("Size {s}").format(
                s=_format_size(store.estimated_download_bytes(missing))
            ),
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        y += self.fonts.base.height + 2
        self.draw.text(
            (0, y),
            _("CDN ok") if reachable else _("CDN unreachable"),
            font=self.fonts.base.font,
            fill=self.colors.get(128 if reachable else 200),
        )

        # Action prompts, anchored from the bottom.
        if missing == 0:
            self.draw.text(
                (0, self.display_class.resY - self.fonts.large.height - 2),
                _("All present"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return
        if not reachable:
            return

        self._draw_action_options()

    def _draw_action_options(self):
        pitch = self.fonts.large.height
        top = self.display_class.resY - 2 * pitch - 4
        bottom = top + pitch
        self.draw.text(
            (10, top),
            _("Download"),
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        self.draw.text(
            (10, bottom),
            _("Cancel"),
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        ind = top if self._option_select == "Download" else bottom
        self.draw.text(
            (0, ind),
            self._RIGHT_ARROW,
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )

    def _draw_progress_bar(self, y, percent):
        bar_x = round(self.display_class.resX * 4 / 128)
        bar_w = self.display_class.resX - 2 * bar_x
        bar_h = round(self.display_class.resY * 12 / 128)
        self.draw.rectangle(
            [bar_x, y, bar_x + bar_w, y + bar_h],
            outline=self.colors.get(64),
        )
        fill_w = int(bar_w * percent / 100)
        if fill_w > 0:
            self.draw.rectangle(
                [bar_x + 1, y + 1, bar_x + fill_w, y + bar_h - 1],
                fill=self.colors.get(255),
            )
        pct_text = f"{percent}%"
        pct_bbox = self.fonts.base.font.getbbox(pct_text)
        pct_x = bar_x + (bar_w - (pct_bbox[2] - pct_bbox[0])) // 2
        pct_y = y + (bar_h - (pct_bbox[3] - pct_bbox[1])) // 2 - pct_bbox[1]
        self.draw.text(
            (pct_x, pct_y),
            pct_text,
            font=self.fonts.base.font,
            fill=self.colors.get(0) if percent > 45 else self.colors.get(192),
        )
        return y + bar_h + 4

    def _draw_running(self):
        progress = self.object_image_downloader.progress()
        y = self.display_class.titlebar_height + 2
        self.draw.text(
            (0, y),
            _("Downloading"),
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        y += self.fonts.bold.height + 6
        y = self._draw_progress_bar(y, progress.percent)
        y += 4
        self.draw.text(
            (0, y),
            _("{done}/{total} images").format(
                done=progress.completed, total=progress.total
            ),
            font=self.fonts.base.font,
            fill=self.colors.get(192),
        )
        # Bottom hint: BACK keeps it running in the background, cancel stops it.
        self.draw.text(
            (0, self.display_class.resY - self.fonts.base.height - 1),
            _("←keep bg  {a}cancel").format(a=self._RIGHT_ARROW),
            font=self.fonts.base.font,
            fill=self.colors.get(96),
        )

    def _draw_done(self):
        progress = self._final
        y = self.display_class.titlebar_height + 2
        title = (
            _("Cancelled") if progress and progress.state == "cancelled" else _("Done")
        )
        self.draw.text(
            (0, y),
            title,
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        y += self.fonts.bold.height + 6
        if progress:
            for label, value in (
                (_("Downloaded"), progress.downloaded),
                (_("Skipped"), progress.skipped),
                (_("Missing"), progress.missing),
                (_("Errors"), progress.errors),
            ):
                self.draw.text(
                    (0, y),
                    f"{label}: {value}",
                    font=self.fonts.base.font,
                    fill=self.colors.get(160),
                )
                y += self.fonts.base.height + 2

    # ------------------------------------------------------------------ #
    # Keys
    # ------------------------------------------------------------------ #
    def _start_download(self):
        with self._lock:
            names = list(self._missing_names)
        if not names or self.object_image_downloader is None:
            return
        if self.object_image_downloader.start(names):
            self._phase = PHASE_RUNNING

    def key_up(self):
        if self._phase == PHASE_PREFLIGHT:
            self._option_select = (
                "Cancel" if self._option_select == "Download" else "Download"
            )

    def key_down(self):
        self.key_up()

    def key_right(self):
        if self._phase == PHASE_PREFLIGHT:
            if self._option_select == "Cancel":
                self.remove_from_stack()
            else:
                self._start_download()
        elif self._phase == PHASE_RUNNING:
            # Explicit cancel (keeps already-downloaded files).
            if self.object_image_downloader:
                self.object_image_downloader.cancel()

    def key_left(self) -> bool:
        # BACK leaves the screen. A running download is app-owned and keeps
        # going in the background (shown by the global title-bar status line);
        # it is not cancelled by simply navigating away.
        return True
