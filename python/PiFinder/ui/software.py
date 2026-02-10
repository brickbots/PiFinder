#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the UI Module classes for
software updates, channel selection, and release notes.
"""

import json
import logging
import time
from typing import Dict, List, Optional

import requests

from PiFinder import utils
from PiFinder.ui.base import UIModule
from PiFinder.ui.ui_utils import TextLayouter

sys_utils = utils.get_sys_utils()
logger = logging.getLogger("UISoftware")

MANIFEST_URL = (
    "https://raw.githubusercontent.com/brickbots/PiFinder"
    "/release/release_manifest.json"
)
VERSION_TXT_URL = (
    "https://raw.githubusercontent.com/brickbots/PiFinder" "/release/version.txt"
)
REQUEST_TIMEOUT = 10


def update_needed(current_version: str, repo_version: str) -> bool:
    """
    Returns true if an update is available.

    Update is available if semver of repo_version is > current_version.
    Returns False on error (safe default — don't offer broken updates).
    """
    try:
        cur = _parse_version(current_version)
        repo = _parse_version(repo_version)
        return repo > cur
    except Exception:
        return False


def _parse_version(version_str: str) -> tuple:
    """
    Parse a version string like '2.4.0' or '2.5.0-beta.1'
    into a comparable tuple.  Pre-release tags sort below
    the same numeric version (2.5.0-beta.1 < 2.5.0).
    """
    version_str = version_str.strip()
    if "-" in version_str:
        numeric_part, pre_release = version_str.split("-", 1)
    else:
        numeric_part = version_str
        pre_release = None

    parts = numeric_part.split(".")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    if pre_release is None:
        return (major, minor, patch, 1, "")
    else:
        return (major, minor, patch, 0, pre_release)


def _fetch_manifest() -> Optional[dict]:
    """Fetch and parse the release manifest JSON. Returns None on failure."""
    try:
        if MANIFEST_URL.startswith("file://"):
            path = MANIFEST_URL[len("file://") :]
            with open(path, "r") as f:
                return json.load(f)
        res = requests.get(MANIFEST_URL, timeout=REQUEST_TIMEOUT)
        if res.status_code == 200:
            return json.loads(res.text)
    except (OSError, json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Could not read release manifest: {e}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not fetch release manifest: {e}")
    return None


def _fetch_version_txt() -> Optional[str]:
    """Fallback: fetch version.txt. Returns version string or None."""
    try:
        res = requests.get(VERSION_TXT_URL, timeout=REQUEST_TIMEOUT)
        if res.status_code == 200:
            return res.text.strip()
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not fetch version.txt: {e}")
    return None


def _filter_upgrades(
    current: str, versions: List[dict]
) -> List[dict]:
    """Return only versions that are newer than current."""
    return [v for v in versions if update_needed(current, v["version"].strip())]


class UISoftware(UIModule):
    """
    UI for updating software versions.
    Supports stable/unstable channels with manifest-based version checking.

    Menu phases (each shows max 3 items, skipped if only one choice):
      channel → version → action
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

        # Parsed manifest data: channel name → list of version dicts
        self._channels: Dict[str, List[dict]] = {}
        self._release_version = "-.-.-"
        self._elipsis_count = 0
        self._go_for_update = False

        # Menu navigation
        # Phases: "channel" or "action"
        self._menu_phase = "action"
        self._selected_channel = "stable"
        self._selected_version: Optional[dict] = None
        self._version_index = 0
        self._options: list = []
        self._option_index = 0

        # Update failure state
        self._update_failed = False
        self._fail_option = "Retry"

    def active(self):
        super().active()
        self._menu_phase = "action"
        self._selected_channel = "stable"
        self._selected_version = None
        self._version_index = 0

    def get_release_version(self):
        """
        Fetches current release version from github.
        Tries manifest first, falls back to version.txt.
        """
        manifest = _fetch_manifest()
        if manifest and "channels" in manifest:
            self._channels = manifest["channels"]
            # Set release version from first stable entry
            stable_versions = self._channels.get("stable", [])
            if stable_versions:
                self._release_version = stable_versions[0]["version"]
            else:
                self._release_version = "Unknown"
            return

        # Fallback to version.txt
        logger.info("Manifest unavailable, falling back to version.txt")
        version = _fetch_version_txt()
        if version:
            self._channels = {
                "stable": [{"version": version, "notes_url": None}]
            }
            self._release_version = version
        else:
            self._release_version = "Unknown"

    def _available_channels(self) -> Dict[str, List[dict]]:
        """Return channels that have updates, filtered by type."""
        current = self._software_version.strip()
        result = {}
        for name, versions in self._channels.items():
            upgrades = _filter_upgrades(current, versions)
            if upgrades:
                result[name] = upgrades
        return result

    def _channel_versions(self) -> List[dict]:
        """Return upgrade versions for the selected channel."""
        available = self._available_channels()
        return available.get(self._selected_channel, [])

    def _rebuild_options(self):
        """Build the option list for the current menu phase."""
        available = self._available_channels()
        options = []

        if self._menu_phase == "channel":
            for name in available:
                options.append(name.capitalize())
        else:
            # Action phase — version selector + actions
            versions = self._channel_versions()
            if len(versions) > 1:
                v = self._selected_version or versions[0]
                options.append(f"v{v['version']}")
            v = self._selected_version or (versions[0] if versions else {})
            options.append("Update")
            if self._selected_version and self._selected_version.get("notes_url"):
                options.append("Notes")
            options.append("Cancel")

        self._options = options
        if self._option_index >= len(self._options):
            self._option_index = 0

    def _enter_best_phase(self):
        """
        Set the menu phase based on what choices exist.
        Skip channel phase when there's only one channel.
        """
        available = self._available_channels()
        channel_names = list(available.keys())

        if len(channel_names) > 1:
            self._menu_phase = "channel"
            self._option_index = 0
            return

        # Single channel
        if channel_names:
            self._selected_channel = channel_names[0]
        else:
            return

        versions = available.get(self._selected_channel, [])
        self._version_index = 0
        if versions:
            self._selected_version = versions[0]
        self._menu_phase = "action"
        self._option_index = 0

    def update_software(self):
        self.message(_("Updating..."), 10)
        if sys_utils.update_software():
            self.message(_("Ok! Restarting..."), 10)
            sys_utils.restart_system()
        else:
            self._update_failed = True

    def _draw_version_header(self):
        """Draw the top section: wifi, current version, release version."""
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

        if self._selected_version:
            update_label = _("Update to")
            update_version = self._selected_version["version"]
        else:
            update_label = _("Update to")
            update_version = self._release_version

        self.draw.text(
            (0, draw_pos),
            update_label,
            font=self.fonts.bold.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        self.draw.text(
            (10, draw_pos),
            f"{update_version}",
            font=self.fonts.bold.font,
            fill=self.colors.get(192),
        )

    def _draw_options(self):
        """Draw the option list at the bottom of the screen."""
        self._rebuild_options()
        option_start_y = 90
        for i, label in enumerate(self._options):
            y = option_start_y + i * 12
            self.draw.text(
                (10, y),
                _(label),
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            if i == self._option_index:
                self.draw.text(
                    (0, y),
                    self._RIGHT_ARROW,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )

    def update(self, force=False):
        time.sleep(1 / 30)
        self.clear_screen()
        self._draw_version_header()

        # Handle update failure screen
        if self._update_failed:
            self.draw.text(
                (10, 90),
                _("Update failed!"),
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 102),
                _("Retry"),
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 114),
                _("Cancel"),
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            ind_pos = 102 if self._fail_option == "Retry" else 114
            self.draw.text(
                (0, ind_pos),
                self._RIGHT_ARROW,
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            return self.screen_update()

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

        available = self._available_channels()
        if not available:
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

        # Update available — enter menu if not already navigating
        if not self._go_for_update:
            self._go_for_update = True
            self._enter_best_phase()

        self._draw_options()
        return self.screen_update()

    def _cycle_option(self, direction: int = 1):
        if self._update_failed:
            self._fail_option = "Cancel" if self._fail_option == "Retry" else "Retry"
            return
        if not self._go_for_update:
            return
        self._option_index = (self._option_index + direction) % len(self._options)

    def key_up(self):
        self._cycle_option(-1)

    def key_down(self):
        self._cycle_option(1)

    def key_left(self):
        available = self._available_channels()
        if self._menu_phase == "action" and len(available) > 1:
            self._menu_phase = "channel"
            self._selected_version = None
            self._option_index = 0
            return False
        return True

    def key_right(self):
        if self._update_failed:
            if self._fail_option == "Retry":
                self._update_failed = False
                self._fail_option = "Retry"
                self.update_software()
            else:
                self._update_failed = False
                self.remove_from_stack()
            return

        if not self._go_for_update:
            return

        selected = self._options[self._option_index]

        if self._menu_phase == "channel":
            self._selected_channel = selected.lower()
            versions = self._channel_versions()
            self._version_index = 0
            self._selected_version = versions[0] if versions else None
            self._menu_phase = "action"
            self._option_index = 0
            return

        # Action phase
        if selected.startswith("v"):
            # Version selector — cycle to next version
            versions = self._channel_versions()
            self._version_index = (self._version_index + 1) % len(versions)
            self._selected_version = versions[self._version_index]
        elif selected == "Cancel":
            self.remove_from_stack()
        elif selected == "Notes":
            notes_url = (
                self._selected_version.get("notes_url")
                if self._selected_version
                else None
            )
            if notes_url:
                self.add_to_stack(
                    {
                        "class": UIReleaseNotes,
                        "notes_url": notes_url,
                    }
                )
        elif selected == "Update":
            self.update_software()


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
                logger.warning(
                    f"Failed to fetch release notes: HTTP {res.status_code}"
                )
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
