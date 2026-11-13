"""The device menu that selects the CelesTrak satellite groups.

The menu stores the selection in ``selection.json``, the same file as the web
page. When the user selects a group that has no file, a background thread
downloads it. The thread puts a message in a queue. The menu shows the
messages one at a time, from the UI thread.

``PiFinder.satellites`` imports Skyfield and SGP4. This module loads it only
when a callback runs, so the menu structure stays light at import time.
"""

import logging
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from PiFinder import utils
from PiFinder.lazy_import import lazy_module
from PiFinder.satellite_groups import AVAILABLE_GROUPS, GROUPS_BY_NAME
from PiFinder.ui.base import UIModule

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


satellites = lazy_module("PiFinder.satellites")

logger = logging.getLogger("UI.SatGroups")

MESSAGE_SECONDS = 2.0


def menu_items() -> list[dict]:
    """One menu item for each group. The value is the CelesTrak group name."""
    return [
        {"name": group.menu_label, "value": group.name} for group in AVAILABLE_GROUPS
    ]


def result_message(result: Any) -> str:
    """The text for the result of ``satellites.refresh_groups``."""
    status = getattr(result, "status", None)
    if status == "downloaded":
        return _("Downloaded")
    if status == "current":
        return _("Up to date")
    if status == "too_soon":
        minutes = max(1, math.ceil(result.wait_seconds / 60.0))
        return _("Wait {minutes} min").format(minutes=minutes)
    if status == "busy":
        return _("Download busy")
    return _("Download failed")


class GroupDownloads:
    """Downloads the requested groups, one at a time, in a background thread.

    The messages for the user wait in a queue until the UI thread takes them.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._messages: list[str] = []
        self._queue: list[tuple[str, Path]] = []
        self._running = False
        self.thread: Optional[threading.Thread] = None

    def post(self, text: str) -> None:
        with self._lock:
            self._messages.append(text)

    def next_message(self) -> Optional[str]:
        with self._lock:
            return self._messages.pop(0) if self._messages else None

    def request(self, group: str, directory: Path) -> None:
        """Put the group in the download queue. Start the thread if needed."""
        with self._lock:
            if any(name == group for name, _directory in self._queue):
                return
            self._queue.append((group, directory))
            if self._running:
                return
            self._running = True
            thread = threading.Thread(
                target=self._run, name="SatGroupDownload", daemon=True
            )
            self.thread = thread
        thread.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._running = False
                    return
                group, directory = self._queue.pop(0)
            self.post(self._download(group, directory))

    def _download(self, group: str, directory: Path) -> str:
        label = GROUPS_BY_NAME[group].menu_label
        try:
            result = satellites.refresh_groups(
                datetime.now(timezone.utc),
                force=True,
                directory=directory,
                groups=(group,),
            )
        except Exception:
            logger.exception("Download of satellite group %s failed", group)
            result = None
        logger.info("Satellite group %s: %s", group, getattr(result, "status", None))
        return result_message(result) + "\n" + label


downloads = GroupDownloads()


def selected_groups(ui_module: UIModule) -> list[str]:
    """The ``values_callback`` of the menu: the stored selection."""
    return list(satellites.selected_groups(utils.satellite_data_dir))


def toggle_group(ui_module: UIModule, group: str, selected: bool) -> None:
    """The ``toggle_callback`` of the menu: store the selection.

    A selected large group gets a message. A selected group without a file
    starts a download.
    """
    directory = utils.satellite_data_dir
    satellites.set_group_enabled(group, selected, directory)
    if not selected:
        return
    info = GROUPS_BY_NAME[group]
    if info.large:
        downloads.post(_("Large group:\nslow passes"))
    if not satellites.group_file(group, directory).exists():
        downloads.post(_("Downloading") + "\n" + info.menu_label)
        downloads.request(group, directory)


def show_next_message(ui_module: UIModule) -> None:
    """The ``update_callback`` of the menu: show the next waiting message."""
    if time.time() < UIModule.message_until:
        return
    text = downloads.next_message()
    if text:
        ui_module.message(text, MESSAGE_SECONDS)
