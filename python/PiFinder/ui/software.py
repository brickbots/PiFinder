#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the UI Module classes for
software updates and NixOS migration.
"""

import logging
import time
from typing import Any, Optional, TYPE_CHECKING

import requests

from PiFinder import utils
from PiFinder.ui.base import UIModule
from PiFinder.ui.ui_utils import TextLayouter

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


sys_utils = utils.get_sys_utils()
logger = logging.getLogger("UISoftware")

REQUEST_TIMEOUT = 10
MIGRATION_GATE_URL = (
    "https://raw.githubusercontent.com/brickbots/PiFinder/release/migration_gate.json"
)

# Secret unlock: 7x square button
_UNLOCK_SEQUENCE = ["square"] * 7

_MIGRATION_VERSION_INFO = {
    "version": "3.0.0",
    "type": "upgrade",
    "migration_size_mb": 292,
    "migration_url": "https://github.com/mrosseel/PiFinder/releases/download/v3.0.0-migration/pifinder-nixos-v3.0.0.tar.zst",
    "migration_sha256_url": "https://github.com/mrosseel/PiFinder/releases/download/v3.0.0-migration/pifinder-nixos-v3.0.0.tar.zst.sha256",
}


def _fetch_migration_config() -> Optional[dict]:
    """Fetch and parse the remote migration config JSON.

    Returns the parsed dict if it contains a usable `nixos_url`; None on
    network error, non-200 response, malformed JSON, or missing url.
    The `nixos_for_everyone` gate is enforced by the caller.
    """
    try:
        res = requests.get(MIGRATION_GATE_URL, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException:
        return None
    if res.status_code != 200:
        return None
    try:
        data = res.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if not data.get("nixos_url"):
        return None
    return data


def update_needed(current_version: str, repo_version: str) -> bool:
    """
    Returns true if an update is available

    Update is available if semvar of repo_version is > current_version
    Also returns True on error to allow be biased towards allowing
    updates if issues
    """
    try:
        _tmp_split = current_version.split(".")
        current_version_compare = (
            int(_tmp_split[0]),
            int(_tmp_split[1]),
            int(_tmp_split[2]),
        )

        _tmp_split = repo_version.split(".")
        repo_version_compare = (
            int(_tmp_split[0]),
            int(_tmp_split[1]),
            int(_tmp_split[2]),
        )

        # tuples compare in significance from first to last element
        return repo_version_compare > current_version_compare

    except Exception:
        return True


class UISoftware(UIModule):
    """
    UI for updating software versions.
    Includes secret 7x square unlock to trigger NixOS migration.
    """

    __title__ = "SOFTWARE"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.version_txt = f"{utils.pifinder_dir}/version.txt"
        self.wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
        with open(self.wifi_txt, "r") as wfs:
            self._wifi_mode = wfs.read()
        with open(self.version_txt, "r") as ver:
            self._software_version = ver.read()

        self._release_version = "-.-.-"
        self._elipsis_count = 0
        self._go_for_update = False
        self._option_select = "Update"

        # Unlock sequence tracking (7x square triggers migration)
        self._key_buffer: list = []

    def _record_key(self, key_name: str):
        """Record a key press for unlock sequence detection."""
        self._key_buffer.append(key_name)
        if len(self._key_buffer) > len(_UNLOCK_SEQUENCE):
            self._key_buffer = self._key_buffer[-len(_UNLOCK_SEQUENCE) :]
        if self._key_buffer == _UNLOCK_SEQUENCE:
            self._key_buffer = []
            # Unlock: self-contained — uses the hardcoded URLs and does not
            # require the remote migration_gate.json to exist.
            self._trigger_migration(dict(_MIGRATION_VERSION_INFO))

    def _trigger_migration(self, version_info: dict):
        """Push UIMigrationConfirm onto the UI stack with the supplied
        version_info (must already contain migration_url and
        migration_sha256_url)."""
        self.message("System Upgrade", 1)
        self.add_to_stack(
            {
                "class": UIMigrationConfirm,
                "version_info": version_info,
                "current_version": self._software_version.strip(),
            }
        )

    def get_release_version(self):
        """
        Fetches current release version from
        github, sets class variable if found.
        Also checks the remote migration config.
        """
        config = _fetch_migration_config()
        if config and config.get("nixos_for_everyone"):
            version_info = dict(_MIGRATION_VERSION_INFO)
            nixos_url = config["nixos_url"]
            version_info["migration_url"] = nixos_url
            version_info["migration_sha256_url"] = f"{nixos_url}.sha256"
            self._trigger_migration(version_info)
            return

        try:
            res = requests.get(
                "https://raw.githubusercontent.com/brickbots/PiFinder/release/version.txt",
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException:
            logger.warning("Could not fetch release version from github")
            self._release_version = "Unknown"
            return

        if res.status_code == 200:
            self._release_version = res.text[:-1]
        else:
            self._release_version = "Unknown"

    def update_software(self):
        self.message(_("Updating..."), 10)
        if sys_utils.update_software():
            self.message(_("Ok! Restarting"), 10)
            sys_utils.restart_system()
        else:
            self.message(_("Error on Upd"), 3)

    def update(self, force=False):
        self.clear_screen()
        draw_pos = self.display_class.titlebar_height + 2
        self.draw.text(
            (0, draw_pos),
            _("Wifi Mode: {}").format(self._wifi_mode),
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 15

        self.draw.text(
            (0, draw_pos),
            _("Current Version"),
            font=self.fonts.bold.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        self.draw.text(
            (10, draw_pos),
            f"{self._software_version}",
            font=self.fonts.bold.font,
            fill=self.colors.get(192),
        )
        draw_pos += 16

        self.draw.text(
            (0, draw_pos),
            _("Release Version"),
            font=self.fonts.bold.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        self.draw.text(
            (10, draw_pos),
            f"{self._release_version}",
            font=self.fonts.bold.font,
            fill=self.colors.get(192),
        )

        if self._wifi_mode != "Client":
            self.draw.text(
                (10, 90),
                _("WiFi must be"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 105),
                _("client mode"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return self.screen_update()

        if self._release_version == "-.-.-":
            # check elipsis count here... if we are at >30 check for
            # release versions
            if self._elipsis_count > 30:
                self.get_release_version()
            self.draw.text(
                (10, 90),
                _("Checking for"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 105),
                _("updates{elipsis}").format(
                    elipsis="." * int(self._elipsis_count / 10)
                ),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self._elipsis_count += 1
            if self._elipsis_count > 39:
                self._elipsis_count = 0
            return self.screen_update()

        if not update_needed(
            self._software_version.strip(), self._release_version.strip()
        ):
            self.draw.text(
                (10, 90),
                _("No Update"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 105),
                _("needed"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return self.screen_update()

        # If we are here, go for update!
        self._go_for_update = True
        self.draw.text(
            (10, 90),
            _("Update Now"),
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        self.draw.text(
            (10, 105),
            _("Cancel"),
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        if self._option_select == "Update":
            ind_pos = 90
        else:
            ind_pos = 105
        self.draw.text(
            (0, ind_pos),
            self._RIGHT_ARROW,
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )

        return self.screen_update()

    def toggle_option(self):
        if not self._go_for_update:
            return
        if self._option_select == "Update":
            self._option_select = "Cancel"
        else:
            self._option_select = "Update"

    def key_square(self):
        self._record_key("square")

    def key_up(self):
        self.toggle_option()

    def key_down(self):
        self.toggle_option()

    def key_right(self):
        if self._option_select == "Cancel":
            self.remove_from_stack()
        else:
            self.update_software()


class UIMigrationConfirm(UIModule):
    """
    Warning screen before initiating NixOS migration.
    Shows version info, warns about irreversibility, requires confirmation.
    """

    __title__ = "UPGRADE"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._version_info = self.item_definition.get("version_info", {})
        self._current_version = self.item_definition.get("current_version", "?")
        self._target_version = self._version_info.get("version", "?")
        self._option_index = 0
        self._options = [_("Confirm"), _("Cancel")]

    def update(self, force=False):
        time.sleep(1 / 30)
        self.clear_screen()
        y = self.display_class.titlebar_height + 2

        self.draw.text(
            (0, y),
            _("Major Upgrade"),
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        y += 14

        self.draw.text(
            (5, y),
            f"{self._current_version} -> {self._target_version}",
            font=self.fonts.bold.font,
            fill=self.colors.get(192),
        )
        y += 16

        # Separator
        self.draw.line([(0, y), (127, y)], fill=self.colors.get(64))
        y += 4

        self.draw.text(
            (0, y),
            _("IRREVERSIBLE"),
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        y += 12

        size_mb = self._version_info.get("migration_size_mb", "?")
        self.draw.text(
            (0, y),
            _("Download: {}MB").format(size_mb),
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        y += 11

        self.draw.text(
            (0, y),
            _("Power + WiFi req"),
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        y += 11

        if not self._version_info.get(
            "migration_sha256_url"
        ) and not self._version_info.get("migration_sha256"):
            self.draw.text(
                (0, y),
                _("No checksum avail."),
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            y += 11

        y += 5

        # Options
        for i, label in enumerate(self._options):
            oy = y + i * 12
            self.draw.text(
                (10, oy),
                label,
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            if i == self._option_index:
                self.draw.text(
                    (0, oy),
                    self._RIGHT_ARROW,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )

        return self.screen_update()

    def key_up(self):
        self._option_index = (self._option_index - 1) % len(self._options)

    def key_down(self):
        self._option_index = (self._option_index + 1) % len(self._options)

    def key_left(self):
        return True

    def key_right(self):
        if self._options[self._option_index] == _("Cancel"):
            self.remove_from_stack()
        elif self._options[self._option_index] == _("Confirm"):
            self.add_to_stack(
                {
                    "class": UIMigrationProgress,
                    "version_info": self._version_info,
                }
            )


class UIMigrationProgress(UIModule):
    """
    Migration download and preparation progress screen.
    Triggers the actual migration via sys_utils.
    """

    __title__ = "UPGRADE"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._version_info = self.item_definition.get("version_info", {})
        self._started = False
        self._status = _("Starting...")
        self._progress = 0
        self._terminal_failure = False
        self._status_layout = TextLayouter(
            self._status,
            draw=self.draw,
            color=self.colors.get(255),
            colors=self.colors,
            font=self.fonts.base,
            available_lines=4,
        )

    def active(self):
        super().active()
        if not self._started:
            self._started = True
            self._start_migration()

    def _start_migration(self):
        """Kick off the migration process in the background."""
        self._status = _("Downloading...")
        try:
            version_info = dict(self._version_info)
            version_info["display_class"] = self.display_class.__class__.__name__
            version_info["display_resolution"] = list(self.display_class.resolution)
            supported_displays = {
                "DisplaySSD1351": (128, 128),
                "DisplaySSD1333": (176, 176),
            }
            display_class = version_info["display_class"]
            display_resolution = tuple(version_info["display_resolution"])
            display_supported = (
                supported_displays.get(display_class) == display_resolution
            )
            display_supported = display_supported or (
                "SSD1333" in display_class and display_resolution == (176, 176)
            )
            if not display_supported:
                logger.error(
                    "Unsupported migration progress renderer display: "
                    f"{display_class} {version_info['display_resolution']}"
                )
                self._status = _("Not supported")
                return
            sys_utils.start_nixos_migration(version_info)
        except AttributeError:
            logger.error("sys_utils.start_nixos_migration not available")
            self._status = _("Not supported")
            self._status_layout.set_text(self._status)
            self._terminal_failure = True
        except Exception as e:
            logger.error(f"Migration failed to start: {e}")
            self._status = _("Failed: ") + str(e)
            self._status_layout.set_text(self._status)
            self._terminal_failure = True

    def update(self, force=False):
        time.sleep(1 / 30)
        self.clear_screen()
        y = self.display_class.titlebar_height + 2

        # Try to read progress from sys_utils. AttributeError happens when
        # running against sys_utils_fake (no migration support); the helper
        # itself swallows OS/JSON errors and returns {}.
        try:
            progress = sys_utils.get_migration_progress()
        except AttributeError:
            progress = None
        if progress:
            try:
                self._progress = int(progress.get("percent", self._progress))
            except (TypeError, ValueError):
                pass  # bad/missing percent — keep prior value
            new_status = progress.get("status", self._status)
            if isinstance(new_status, str) and new_status != self._status:
                self._status = new_status
                self._status_layout.set_text(self._status)

        self.draw.text(
            (0, y),
            _("System Upgrade"),
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        y += 20

        # Progress bar
        bar_x, bar_w, bar_h = 4, 120, 12
        self.draw.rectangle(
            [bar_x, y, bar_x + bar_w, y + bar_h],
            outline=self.colors.get(64),
        )
        fill_w = int(bar_w * self._progress / 100)
        if fill_w > 0:
            self.draw.rectangle(
                [bar_x + 1, y + 1, bar_x + fill_w, y + bar_h - 1],
                fill=self.colors.get(255),
            )
        pct_text = f"{self._progress}%"
        pct_bbox = self.fonts.base.font.getbbox(pct_text)
        pct_w = pct_bbox[2] - pct_bbox[0]
        pct_h = pct_bbox[3] - pct_bbox[1]
        pct_x = bar_x + (bar_w - pct_w) // 2
        pct_y = y + (bar_h - pct_h) // 2 - pct_bbox[1]
        self.draw.text(
            (pct_x, pct_y),
            pct_text,
            font=self.fonts.base.font,
            fill=self.colors.get(0) if self._progress > 45 else self.colors.get(192),
        )
        y += bar_h + 4

        # Use TextLayouter for scrollable status text
        self._status_layout.draw((0, y))

        return self.screen_update()

    def key_up(self):
        self._status_layout.previous()

    def key_down(self):
        self._status_layout.next()

    def key_left(self):
        # Allow exit only if the migration never actually started (e.g.,
        # pre-flight refused due to missing checksum or unsupported display).
        # Once the bash script is running, going back is unsafe.
        if self._terminal_failure:
            self.remove_from_stack()
            return True
        return False


class UIReleaseNotes(UIModule):
    """
    Scrollable release notes viewer.
    Fetches markdown from a URL and displays as plain text.
    """

    __title__ = "NOTES"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._notes_url = self.item_definition.get("notes_url", "")
        self._loaded = False
        self._error = False
        self._text_layout = TextLayouter(
            "",
            draw=self.draw,
            color=self.colors.get(255),
            colors=self.colors,
            font=self.fonts.base,
            available_lines=9,
        )

    def active(self):
        super().active()
        if not self._loaded:
            self._fetch_notes()

    def _fetch_notes(self):
        """Fetch release notes from the configured URL."""
        try:
            res = requests.get(self._notes_url, timeout=REQUEST_TIMEOUT)
            if res.status_code == 200:
                text = _strip_markdown(res.text)
                self._text_layout.set_text(text)
                self._loaded = True
            else:
                self._error = True
                logger.warning(f"Failed to fetch release notes: HTTP {res.status_code}")
        except requests.exceptions.RequestException as e:
            self._error = True
            logger.warning(f"Failed to fetch release notes: {e}")

    def update(self, force=False):
        time.sleep(1 / 30)
        self.clear_screen()
        draw_pos = self.display_class.titlebar_height + 2

        if self._error:
            self.draw.text(
                (10, draw_pos + 20),
                _("Could not load"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, draw_pos + 35),
                _("release notes"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return self.screen_update()

        if not self._loaded:
            self.draw.text(
                (10, draw_pos + 20),
                _("Loading..."),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return self.screen_update()

        self._text_layout.draw((0, draw_pos))
        return self.screen_update()

    def key_down(self):
        self._text_layout.next()

    def key_up(self):
        self._text_layout.previous()

    def key_left(self):
        return True


def _strip_markdown(text: str) -> str:
    """
    Minimal markdown stripping for plain-text display on OLED.
    Removes common markdown syntax while keeping readable text.
    """
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip("#").strip()
        stripped = stripped.replace("**", "").replace("__", "")
        stripped = stripped.replace("*", "").replace("_", "")
        while "[" in stripped and "](" in stripped:
            start = stripped.index("[")
            mid = stripped.index("](", start)
            end = stripped.index(")", mid)
            link_text = stripped[start + 1 : mid]
            stripped = stripped[:start] + link_text + stripped[end + 1 :]
        stripped = stripped.replace("`", "")
        lines.append(stripped)
    return "\n".join(lines)
