"""The device menu that selects the CelesTrak satellite groups.

The menu stores the selection in ``selection.json``, the same file as the web
page. When the user selects a group that has no file, a background thread
downloads it. The thread puts a message in a queue. The main loop shows the
messages one at a time, on any screen. The menu shows them too.

A selected group whose last download failed has a "!" mark. A select of
such a group shows the reason.

"Update now", the first item of the menu, downloads the selected groups
again. A group downloads at most once in MIN_FORCED_DOWNLOAD_SECONDS (2 h).

``PiFinder.satellites`` imports Skyfield and SGP4. This module loads it only
when a callback runs, so the menu structure stays light at import time.
"""

import functools
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
satellite_catalog = lazy_module("PiFinder.satellite_catalog")

logger = logging.getLogger("UI.SatGroups")

MESSAGE_SECONDS = 2.0
# A message with an error reason stays longer.
ERROR_MESSAGE_SECONDS = 4.0
FAILED_MARK = "!"


def menu_items() -> list[dict]:
    """One menu item for each group. The value is the CelesTrak group name."""
    return [
        {
            "name": group.menu_label,
            "value": group.name,
            "name_suffix_callback": functools.partial(failed_mark, group.name),
        }
        for group in AVAILABLE_GROUPS
    ]


def reason_text(error: str) -> str:
    """The short device text for the reason of a failed download.

    ``satellites.download_error_text`` makes the reason. The screen shows
    about 16 characters on a line.
    """
    if error == "CelesTrak has no data":
        return _("Group empty now")
    if error == "No network":
        return _("No network")
    if error == "No answer from server":
        return _("Server timeout")
    if error == "No valid data":
        return _("No valid data")
    if error.startswith("Refused by CelesTrak"):
        return _("Refused (403)")
    if error.startswith("Server error ") or error.startswith("HTTP error "):
        return error
    return _("Download failed")


def wait_message(seconds: float) -> str:
    """The short wait text of the device: "Wait 4 min", "Wait 1h45".

    The text fits a line of the 128 px screen.
    """
    minutes = max(1, math.ceil(seconds / 60.0))
    if minutes < 60:
        # TRANSLATORS: A catalog download was done a short time ago
        return _("Wait {minutes} min").format(minutes=minutes)
    # TRANSLATORS: A wait of hours and minutes, for example "Wait 1h45"
    return _("Wait {hours}h{minutes:02d}").format(
        hours=minutes // 60, minutes=minutes % 60
    )


def result_message(result: Any) -> str:
    """The text for the result of ``satellites.refresh_groups``."""
    status = getattr(result, "status", None)
    if status == "downloaded":
        return _("Downloaded")
    if status == "current":
        return _("Up to date")
    if status == "too_soon":
        return wait_message(result.wait_seconds)
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

    def post_result(self, result: Any) -> None:
        """Post the message for the result of a download of the catalog."""
        self.post(catalog_result_message(result))

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
        text = result_message(result) + "\n" + label
        error = result.error_of(group) if result is not None else ""
        if error:
            text += "\n" + reason_text(error)
        return text


def catalog_result_message(result: Any) -> str:
    """The text for the result of a forced download of the catalog."""
    text = result_message(result)
    failed = tuple(getattr(result, "failed", ()))
    if failed:
        labels = [GROUPS_BY_NAME[group].menu_label for group in failed]
        text += "\n" + ", ".join(labels)
        error = result.error_of(failed[0])
        if error:
            text += "\n" + reason_text(error)
    return text


downloads = GroupDownloads()


# The selection file key (path, inode, change time in ns) and the groups read
# from it. Each write replaces the file, so the inode changes on each write.
_selection_cache: tuple[Optional[tuple[Path, int, int]], list[str]] = (None, [])


def selected_groups(ui_module: UIModule) -> list[str]:
    """The ``values_callback`` of the menu: the stored selection.

    The menu calls it on each frame, so the file is read again only when
    its inode or its change time is different.
    """
    global _selection_cache
    directory = utils.satellite_data_dir
    path = satellites.selection_file(directory)
    try:
        stat = path.stat()
        key: Optional[tuple[Path, int, int]] = (path, stat.st_ino, stat.st_mtime_ns)
    except OSError:
        key = (path, -1, -1)
    if key != _selection_cache[0]:
        _selection_cache = (key, list(satellites.selected_groups(directory)))
    return list(_selection_cache[1])


def update_now(ui_module: UIModule) -> None:
    """The callback of "Update now": a forced download of the selected groups.

    The messages go to the queue. A download that is too soon after the
    last one gives the wait. The satellite catalog downloads in its thread
    and posts the result. Without a catalog, each group downloads in the
    thread of ``downloads``.
    """
    directory = utils.satellite_data_dir
    groups = satellites.selected_groups(directory)
    if not groups:
        downloads.post(_("No groups") + "\n" + _("selected"))
        return
    now = datetime.now(timezone.utc)
    waits = satellites.forced_download_wait(now, directory, groups)
    wait = min(waits.values(), default=0.0)
    if wait > 0:
        downloads.post(wait_message(wait))
        return
    # TRANSLATORS: A download of the satellite groups starts
    downloads.post(_("Updating..."))
    catalog = satellite_catalog.active_catalog()
    if catalog is None:
        for group in groups:
            downloads.request(group, directory)
        return
    wait_seconds = catalog.refresh()
    if wait_seconds:
        downloads.post(wait_message(wait_seconds))


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
        return
    error = failed_error(group)
    if error is not None:
        downloads.post(
            _("Update failed") + "\n" + info.menu_label + "\n" + reason_text(error)
        )


# The status file key (path, inode, change time in ns) and the failed groups
# with their reasons. Each write replaces the file, so the inode changes.
_status_cache: tuple[Optional[tuple[Path, int, int]], dict[str, str]] = (None, {})


def failed_groups() -> dict[str, str]:
    """The groups whose last download failed, with the stored reason.

    The menu asks on each frame for each row, so the file is read again
    only when its inode or its change time is different.
    """
    global _status_cache
    directory = utils.satellite_data_dir
    path = satellites.download_status_file(directory)
    try:
        stat = path.stat()
        key: Optional[tuple[Path, int, int]] = (path, stat.st_ino, stat.st_mtime_ns)
    except OSError:
        key = (path, -1, -1)
    if key != _status_cache[0]:
        now = datetime.now(timezone.utc)
        failed = {
            group: entry.error
            for group, entry in satellites.load_download_status(directory).items()
            if entry.current_result(now) == satellites.RESULT_FAILED
        }
        _status_cache = (key, failed)
    return dict(_status_cache[1])


def failed_error(group: str) -> Optional[str]:
    """The reason of the failed last download of ``group``, or None."""
    return failed_groups().get(group)


def failed_mark(group: str, ui_module: UIModule) -> str:
    """The ``name_suffix_callback`` of a group: "!" on a selected group
    whose last download failed."""
    if group not in selected_groups(ui_module):
        return ""
    return FAILED_MARK if failed_error(group) is not None else ""


def show_next_message(ui_module: Any) -> None:
    """Show the next waiting message on ``ui_module``.

    The ``update_callback`` of the menu and the main loop call this. A
    UIModule and the MenuManager both have ``message``.
    """
    if time.time() < UIModule.message_until:
        return
    text = downloads.next_message()
    if text:
        lines = text.count("\n") + 1
        seconds = ERROR_MESSAGE_SECONDS if lines > 2 else MESSAGE_SECONDS
        ui_module.message(text, seconds, size=message_box(ui_module, lines))


def message_box(ui_module: Any, lines: int) -> Optional[tuple[int, int, int, int]]:
    """A message box with room for ``lines`` lines, or None for the
    standard box of two lines."""
    if lines <= 2:
        return None
    display = ui_module.display_class
    height = round(display.resY * (12 + 16 * lines) / 128)
    top = (display.resY - height) // 2
    return (5, top, display.resX - 5, top + height)
