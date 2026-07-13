#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
UI modules for software updates, channel selection, and release notes.

Channels:
  - stable:   release entries from update-manifest.json
  - beta:     prerelease entries from update-manifest.json
  - unstable: trunk + testable PR entries from update-manifest.json
"""

import json
import logging
import re
import time
from typing import Dict, List, Optional, TYPE_CHECKING

import requests

if TYPE_CHECKING:
    # At runtime PiFinder.i18n gettext-installs _ into builtins; mypy only
    # sees it inside annotated functions, so give it a signature here.
    def _(message: str) -> str: ...


from PiFinder import utils
from PiFinder.ui.base import UIModule
from PiFinder.ui.ui_utils import TextLayouter, TextLayouterScroll

sys_utils = utils.get_sys_utils()
logger = logging.getLogger("UISoftware")

# --- Update channel source -----------------------------------------------------
# CI publishes generated update metadata to a metadata-only branch. Devices read
# one raw JSON file instead of calling the GitHub REST API, so they do not burn
# unauthenticated rate limits.
MANIFEST_REPO = "brickbots/PiFinder"
MANIFEST_BRANCH = "nixos-manifest"
# ------------------------------------------------------------------------------
UPDATE_MANIFEST_URL = (
    f"https://raw.githubusercontent.com/{MANIFEST_REPO}/"
    f"{MANIFEST_BRANCH}/update-manifest.json"
)
REQUEST_TIMEOUT = 10
_STORE_PATH_RE = re.compile(r"^/nix/store/[a-z0-9]+-[A-Za-z0-9._+=?,-]+$")


def _entry_from_manifest(item: dict, channel: str) -> Optional[dict]:
    label = item.get("label")
    if not isinstance(label, str) or not label:
        return None

    title = item.get("title") or item.get("subtitle") or label
    entry = {
        "label": label,
        "ref": item.get("store_path"),
        "notes": item.get("notes") or None,
        "version": item.get("version") or label,
        "subtitle": title,
        "channel": channel,
        "migration_url": item.get("migration_url") or None,
        "migration_sha256_url": item.get("migration_sha256_url") or None,
    }
    if item.get("kind") == "trunk":
        entry["is_trunk"] = True

    store_path = item.get("store_path")
    available = item.get("available", bool(store_path))
    if not available or not isinstance(store_path, str):
        entry["ref"] = None
        entry["unavailable"] = True
        reason = item.get("reason")
        if reason:
            entry["subtitle"] = f"{title} ({reason})"
    elif not _STORE_PATH_RE.fullmatch(store_path):
        entry["ref"] = None
        entry["unavailable"] = True
        entry["subtitle"] = f"{title} (invalid build)"

    return entry


def _fetch_update_manifest() -> dict[str, list[dict]]:
    """
    Fetch CI-generated update metadata.
    Raises RequestException for network failures so the caller can show offline.
    """
    res = requests.get(UPDATE_MANIFEST_URL, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    manifest = res.json()
    if manifest.get("schema") != 1:
        raise ValueError("unsupported update manifest schema")

    channels: dict[str, list[dict]] = {}
    manifest_channels = manifest.get("channels", {})
    if not isinstance(manifest_channels, dict):
        raise ValueError("invalid update manifest channels")

    for channel in ("stable", "beta", "unstable"):
        entries: list[dict] = []
        raw_entries = manifest_channels.get(channel, [])
        if not isinstance(raw_entries, list):
            continue
        for item in raw_entries:
            if not isinstance(item, dict):
                continue
            entry = _entry_from_manifest(item, channel)
            if entry is not None:
                entries.append(entry)
        channels[channel] = entries

    return channels


def _current_store_path() -> Optional[str]:
    """Store path of the running build, or None when unknown.

    The store path — not the version string — is a build's identity: a re-cut
    release keeps its version/label but is a different system. Prefer
    current-build.json (it names the base store path even on a camera-specialised
    device), but only when it actually describes the running system: it is
    written before the reboot, so a failed boot or rollback can leave it naming a
    build that isn't running. When stale, fall back to the actually-running
    system so the update list hides the real build, not a phantom one.
    """
    try:
        with open(utils.current_build_json) as f:
            recorded = json.load(f).get("store_path") or None
    except (OSError, ValueError):
        recorded = None
    if recorded and utils.build_is_running(recorded):
        return recorded
    return utils.running_system_store_path()


def _hide_current_build(entries: List[dict], current_ref: Optional[str]) -> List[dict]:
    """Hide only the exact running build, matched by store path.

    A same-version entry with a different store path (e.g. a re-cut release)
    is a real upgrade and must stay visible. When the current build is
    unknown, nothing is hidden — offering the running build is harmless,
    hiding a real upgrade is not.
    """
    if not current_ref:
        return list(entries)
    return [e for e in entries if e.get("ref") != current_ref]


MIGRATION_GATE_URL = (
    "https://raw.githubusercontent.com/brickbots/PiFinder/release/migration_gate.json"
)

# Secret unlock: 7x square button
_UNLOCK_SEQUENCE = ["square"] * 7

# Migration targets are read from the update manifest, consulted in descending
# stability; the first available entry carrying a migration tarball wins.
_MIGRATION_CHANNELS = ("stable", "beta", "unstable")


def _fetch_migration_config() -> Optional[dict]:
    """Fetch and parse the remote migration gate JSON.

    Returns the parsed dict on success; None on network error, non-200
    response, or malformed JSON. Only the `nixos_for_everyone` flag is used by
    the caller — the tarball itself comes from the update manifest.
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
    return data


def _fetch_download_size_mb(url: str) -> Optional[int]:
    """Return the tarball download size in MB from a HEAD request, or None.

    GitHub release assets 302-redirect to a signed URL whose response carries
    the real Content-Length, so redirects must be followed. Returns None on
    network error, non-200 status, or a missing/unparseable Content-Length.
    """
    try:
        res = requests.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException:
        return None
    if res.status_code != 200:
        return None
    length = res.headers.get("Content-Length")
    if length is None:
        return None
    try:
        return round(int(length) / (1024 * 1024))
    except (TypeError, ValueError):
        return None


def _migration_version_info_from_manifest() -> Optional[dict]:
    """Select a migration target from the update manifest.

    Walks channels stable -> beta -> unstable and returns version_info for the
    first available entry that carries a migration tarball, or None if the
    manifest can't be fetched or has no such entry.
    """
    try:
        manifest_channels = _fetch_update_manifest()
    except (requests.exceptions.RequestException, ValueError):
        return None
    for channel in _MIGRATION_CHANNELS:
        entries = manifest_channels.get(channel, [])
        for entry in entries:
            url = entry.get("migration_url")
            sha_url = entry.get("migration_sha256_url")
            if entry.get("unavailable") or not url or not sha_url:
                continue
            version_info = {
                "version": entry.get("version", "?"),
                "type": "upgrade",
                "migration_url": url,
                "migration_sha256_url": sha_url,
            }
            # Size comes from a live HEAD on the tarball; omitted on failure
            # (the confirm screen then shows "?").
            size_mb = _fetch_download_size_mb(url)
            if size_mb is not None:
                version_info["migration_size_mb"] = size_mb
            return version_info
    return None


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
    Software update UI.

    Phases:
      loading   - animated "Checking for updates..."
      browse    - header (version + channel selector) + scrollable version list
      confirm   - selected version details + Install / Notes / Cancel
      upgrading - progress bar with download progress, then reboot
      failed    - update failed + Retry / Cancel
    """

    __title__ = "SOFTWARE"
    MAX_VISIBLE = 4

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
        with open(self.wifi_txt, "r") as f:
            self._wifi_mode = f.read().strip()
        self._software_version = utils.get_version()
        self._software_subtitle: Optional[str] = None

        self._channels: Dict[str, List[dict]] = {}
        self._manifest_channels: Dict[str, List[dict]] = {}
        self._channel_names: List[str] = []
        self._channel_index = 0

        self._version_list: List[dict] = []
        self._list_index = 0
        self._scroll_offset = 0

        self._phase = "loading"
        self._focus = "channel"  # "channel" or "list" (browse phase)
        self._elipsis_count = 0

        self._selected_version: Optional[dict] = None
        self._confirm_options: List[str] = []
        self._confirm_index = 0

        self._fail_option = "Retry"
        self._fail_reason = ""
        self._unstable_entries: List[dict] = []

        # Unlock sequence tracking (7x square triggers a manifest-sourced
        # in-place migration).
        self._key_buffer: List[str] = []

        self._scrollers: Dict[str, TextLayouterScroll] = {}
        self._scroller_phase: Optional[str] = None
        self._scroller_index: Optional[int] = None

    def active(self):
        super().active()
        self._phase = "loading"
        self._elipsis_count = 0
        self._focus = "channel"
        self._channel_index = 0
        self._list_index = 0
        self._scroll_offset = 0
        self._selected_version = None
        self._scrollers = {}
        self._scroller_phase = None
        self._scroller_index = None

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _fetch_channels(self):
        # Rollback targets come from local, immutable generation data, so they
        # are available even when the manifest can't be fetched — which is
        # exactly when rollback matters most.
        try:
            rollback = sys_utils.list_rollback_targets()
        except Exception as e:  # never let rollback listing break the screen
            logger.warning("Could not list rollback targets: %s", e)
            rollback = []

        try:
            manifest_channels = _fetch_update_manifest()
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.warning("Software update check failed (offline/invalid?): %s", e)
            if not rollback:
                self._phase = "offline"
                return
            # Network channels are unavailable, but we can still offer Rollback.
            self._manifest_channels = {}
            self._channels = {"rollback": rollback}
            self._channel_names = list(self._channels.keys())
            self._channel_index = 0
            self._refresh_version_list()
            self._phase = "browse"
            return

        self._manifest_channels = manifest_channels
        self._channels = {
            "stable": manifest_channels.get("stable", []),
            "beta": manifest_channels.get("beta", []),
        }

        if self.config_object.get_option("dev_mode", False):
            self._unstable_entries = manifest_channels.get("unstable", [])
            self._channels["unstable"] = self._unstable_entries

        if rollback:
            self._channels["rollback"] = rollback

        # Try to find subtitle for current version from fetched entries
        self._software_subtitle = self._find_current_subtitle()

        self._channel_names = list(self._channels.keys())
        self._channel_index = 0
        self._refresh_version_list()
        self._phase = "browse"

    def _find_current_subtitle(self) -> Optional[str]:
        """Find a subtitle for the running build.

        Matches by store path (the build's identity) first, falling back to
        the version string when the current store path is unknown.
        """
        current_ref = _current_store_path()
        for entries in self._channels.values():
            for entry in entries:
                if current_ref and entry.get("ref") == current_ref:
                    return entry.get("subtitle")
                if not current_ref and entry.get("version") == self._software_version:
                    return entry.get("subtitle")

        return None

    def _refresh_version_list(self):
        if not self._channel_names:
            self._version_list = []
            return
        channel = self._channel_names[self._channel_index]
        entries = self._channels.get(channel, [])
        if channel == "rollback":
            self._version_list = entries
        else:
            self._version_list = _hide_current_build(entries, _current_store_path())
        self._list_index = 0
        self._scroll_offset = 0
        self._scrollers = {}
        self._scroller_phase = None
        self._scroller_index = None

    def _get_scrollspeed_config(self):
        scroll_dict = {
            "Off": 0,
            "Fast": TextLayouterScroll.FAST,
            "Med": TextLayouterScroll.MEDIUM,
            "Slow": TextLayouterScroll.SLOW,
        }
        scrollspeed = self.config_object.get_option("text_scroll_speed", "Med")
        return scroll_dict[scrollspeed]

    def _get_scroller(self, key: str, text: str, font, color, width: int):
        """Get or create a cached scroller, reset cache on phase/index change."""
        phase_index = (self._phase, self._list_index)
        if (self._scroller_phase, self._scroller_index) != phase_index:
            self._scrollers = {}
            self._scroller_phase = self._phase
            self._scroller_index = self._list_index

        if key not in self._scrollers:
            self._scrollers[key] = TextLayouterScroll(
                text,
                draw=self.draw,
                color=color,
                font=font,
                width=width,
                scrollspeed=self._get_scrollspeed_config(),
            )
        return self._scrollers[key]

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_separator(self, y):
        self.draw.line([(0, y), (127, y)], fill=self.colors.get(64))

    def _draw_loading(self):
        y = self.display_class.titlebar_height + 2
        ver_scroller = self._get_scroller(
            "loading_ver",
            self._software_version,
            self.fonts.bold,
            self.colors.get(255),
            self.fonts.bold.line_length,
        )
        ver_scroller.draw((0, y))
        dots = "." * (self._elipsis_count // 10)
        self.draw.text(
            (10, 90),
            _("Checking for"),
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        self.draw.text(
            (10, 105),
            _("updates{elipsis}").format(elipsis=dots),
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        self._elipsis_count += 1
        if self._elipsis_count > 39:
            self._elipsis_count = 0

    def _draw_wifi_warning(self):
        y = self.display_class.titlebar_height + 2
        ver_scroller = self._get_scroller(
            "wifi_ver",
            self._software_version,
            self.fonts.bold,
            self.colors.get(255),
            self.fonts.bold.line_length,
        )
        ver_scroller.draw((0, y))
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

    def _draw_offline(self):
        y = self.display_class.titlebar_height + 2
        ver_scroller = self._get_scroller(
            "offline_ver",
            self._software_version,
            self.fonts.bold,
            self.colors.get(255),
            self.fonts.bold.line_length,
        )
        ver_scroller.draw((0, y))
        self.draw.text(
            (10, 90),
            _("No internet -"),
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        self.draw.text(
            (10, 105),
            _("check WiFi"),
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )

    def _draw_browse(self):
        y = self.display_class.titlebar_height + 2

        # Current version
        ver_scroller = self._get_scroller(
            "browse_cur_ver",
            self._software_version,
            self.fonts.bold,
            self.colors.get(255),
            self.fonts.bold.line_length,
        )
        ver_scroller.draw((0, y))
        y += 12
        if self._software_subtitle:
            sub_scroller = self._get_scroller(
                "browse_cur_sub",
                self._software_subtitle,
                self.fonts.base,
                self.colors.get(128),
                self.fonts.base.line_length,
            )
            sub_scroller.draw((0, y))
            y += 12
        else:
            y += 2

        # Channel selector
        channel_name = (
            self._channel_names[self._channel_index].capitalize()
            if self._channel_names
            else "---"
        )
        if self._focus == "channel":
            self.draw.text(
                (0, y),
                self._RIGHT_ARROW,
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, y),
                channel_name,
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
        else:
            self.draw.text(
                (10, y),
                channel_name,
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
        y += 14

        self._draw_separator(y)
        y += 4

        # Version list
        if not self._version_list:
            self.draw.text(
                (10, y + 10),
                _("No versions"),
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            self.draw.text(
                (10, y + 22),
                _("available"),
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            return

        label_width = self.fonts.base.line_length - 2
        current_y = y
        for i in range(len(self._version_list)):
            idx = self._scroll_offset + i
            if idx >= len(self._version_list):
                break
            entry = self._version_list[idx]
            label = entry["label"]
            subtitle = entry.get("subtitle", "")

            if self._focus == "list" and idx == self._list_index:
                if current_y + 24 > 128:
                    break
                self.draw.text(
                    (0, current_y),
                    self._RIGHT_ARROW,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )
                scroller = self._get_scroller(
                    "browse_label",
                    label,
                    self.fonts.bold,
                    self.colors.get(255),
                    label_width,
                )
                scroller.draw((10, current_y))
                current_y += 12
                if subtitle:
                    sub_scroller = self._get_scroller(
                        "browse_sub",
                        subtitle,
                        self.fonts.base,
                        self.colors.get(128),
                        label_width,
                    )
                    sub_scroller.draw((10, current_y))
                current_y += 12
            else:
                if current_y + 12 > 128:
                    break
                # The trunk ("main") row stands out from the PR rows: bold and
                # brighter, with a leading dot.
                if entry.get("is_trunk"):
                    self.draw.text(
                        (10, current_y),
                        f"• {label}"[:label_width],
                        font=self.fonts.bold.font,
                        fill=self.colors.get(255),
                    )
                else:
                    self.draw.text(
                        (10, current_y),
                        label[:label_width],
                        font=self.fonts.base.font,
                        fill=self.colors.get(192),
                    )
                current_y += 12

    def _draw_confirm(self):
        y = self.display_class.titlebar_height + 2

        self.draw.text(
            (0, y),
            _("Update to:"),
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        y += 14

        label_width = self.fonts.base.line_length
        version_label = (
            self._selected_version.get("version") or self._selected_version["label"]
        )
        scroller = self._get_scroller(
            "confirm_label",
            version_label,
            self.fonts.bold,
            self.colors.get(255),
            label_width,
        )
        scroller.draw((0, y))
        y += 12

        subtitle = self._selected_version.get("subtitle", "")
        if subtitle:
            sub_scroller = self._get_scroller(
                "confirm_sub",
                subtitle,
                self.fonts.base,
                self.colors.get(128),
                label_width,
            )
            sub_scroller.draw((0, y))
        y += 14

        self._draw_separator(y)
        y += 4

        for i, opt in enumerate(self._confirm_options):
            item_y = y + i * 12
            if i == self._confirm_index:
                self.draw.text(
                    (0, item_y),
                    self._RIGHT_ARROW,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )
                self.draw.text(
                    (10, item_y),
                    _(opt),
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )
            else:
                self.draw.text(
                    (10, item_y),
                    _(opt),
                    font=self.fonts.base.font,
                    fill=self.colors.get(192),
                )

    def _draw_failed(self):
        y = self.display_class.titlebar_height + 20
        reason = self._fail_reason or _("Update failed!")
        for line in reason.split("\n"):
            self.draw.text(
                (10, y),
                line,
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            y += 14
        y += 6
        for label in ("Retry", "Cancel"):
            if self._fail_option == label:
                self.draw.text(
                    (0, y),
                    self._RIGHT_ARROW,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )
            self.draw.text(
                (10, y),
                _(label),
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            y += 12

    def _record_key(self, key_name: str):
        """Record a key press for the migration unlock sequence (7x square)."""
        self._key_buffer.append(key_name)
        if len(self._key_buffer) > len(_UNLOCK_SEQUENCE):
            self._key_buffer = self._key_buffer[-len(_UNLOCK_SEQUENCE) :]
        if self._key_buffer == _UNLOCK_SEQUENCE:
            self._key_buffer = []
            # Unlock: offer the first available migration target from the
            # manifest, ignoring the nixos_for_everyone gate (that governs only
            # the public path).
            version_info = _migration_version_info_from_manifest()
            if version_info:
                self._trigger_migration(version_info)
            else:
                self.message(_("No release found"), 2)

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

    # ------------------------------------------------------------------
    # Main update loop
    # ------------------------------------------------------------------

    def update(self, force=False):
        self.clear_screen()

        if self._phase == "upgrading":
            self._draw_upgrading()
            return self.screen_update()

        if self._phase == "failed":
            self._draw_failed()
            return self.screen_update()

        if self._wifi_mode != "Client":
            self._draw_wifi_warning()
            return self.screen_update()

        if self._phase == "loading":
            if self._elipsis_count > 30:
                self._fetch_channels()
                # phase is now "browse" or "offline", fall through
            else:
                self._draw_loading()
                return self.screen_update()

        if self._phase == "offline":
            self._draw_offline()
            return self.screen_update()

        if self._phase == "browse":
            self._draw_browse()
        elif self._phase == "confirm":
            self._draw_confirm()

        return self.screen_update()

    # ------------------------------------------------------------------
    # Key handlers
    # ------------------------------------------------------------------

    def key_up(self):
        if self._phase == "upgrading":
            return
        if self._phase == "failed":
            self._fail_option = "Cancel" if self._fail_option == "Retry" else "Retry"
        elif self._phase == "browse":
            if self._focus == "list":
                if self._list_index == 0:
                    self._focus = "channel"
                else:
                    self._list_index -= 1
                    if self._list_index < self._scroll_offset:
                        self._scroll_offset = self._list_index
        elif self._phase == "confirm":
            if self._confirm_index > 0:
                self._confirm_index -= 1

    def key_down(self):
        if self._phase == "upgrading":
            return
        if self._phase == "failed":
            self._fail_option = "Cancel" if self._fail_option == "Retry" else "Retry"
        elif self._phase == "browse":
            if self._focus == "channel":
                if self._version_list:
                    self._focus = "list"
                    self._list_index = 0
                    self._scroll_offset = 0
            elif self._focus == "list":
                if self._list_index < len(self._version_list) - 1:
                    self._list_index += 1
                    if self._list_index >= self._scroll_offset + self.MAX_VISIBLE:
                        self._scroll_offset = self._list_index - self.MAX_VISIBLE + 1
        elif self._phase == "confirm":
            if self._confirm_index < len(self._confirm_options) - 1:
                self._confirm_index += 1

    def key_right(self):
        if self._phase == "upgrading":
            return
        if self._phase == "failed":
            if self._fail_option == "Retry":
                # Re-enters update_software() → "upgrading" phase, so Retry
                # reuses the same progress UI as the first attempt.
                self.update_software()
            else:
                self.remove_from_stack()
        elif self._phase == "browse":
            if self._focus == "channel" and self._channel_names:
                self._channel_index = (self._channel_index + 1) % len(
                    self._channel_names
                )
                self._refresh_version_list()
            elif self._focus == "list" and self._version_list:
                self._selected_version = self._version_list[self._list_index]
                self._confirm_options = []
                if not self._selected_version.get("unavailable"):
                    self._confirm_options.append("Install")
                if self._selected_version.get("notes"):
                    self._confirm_options.append("Notes")
                self._confirm_options.append("Cancel")
                self._confirm_index = 0
                self._phase = "confirm"
        elif self._phase == "confirm":
            opt = self._confirm_options[self._confirm_index]
            if opt == "Install":
                self.update_software()
            elif opt == "Notes":
                notes = self._selected_version.get("notes")
                if notes:
                    self.add_to_stack({"class": UIReleaseNotes, "notes_text": notes})
            elif opt == "Cancel":
                self._phase = "browse"

    def key_left(self):
        if self._phase == "upgrading":
            return False
        if self._phase == "confirm":
            self._phase = "browse"
            return False
        return True

    def key_square(self):
        self._record_key("square")

    def key_number(self, number):
        self._key_buffer = []

    # ------------------------------------------------------------------
    # Update action
    # ------------------------------------------------------------------

    def update_software(self):
        if not self._selected_version:
            return
        if self._selected_version.get("unavailable"):
            self._phase = "failed"
            self._fail_reason = _("Version no\nlonger available")
            self._fail_option = "Cancel"
            return
        self._phase = "upgrading"
        self.clear_screen()
        self._draw_upgrading()
        self.screen_update()

        ref = self._selected_version.get("ref") or "release"
        selection = {
            "ref": ref,
            "label": self._selected_version.get("label"),
            "version": self._selected_version.get("version"),
            "channel": self._selected_version.get("channel"),
        }
        if not sys_utils.update_software(ref=ref, selection=selection):
            self._phase = "failed"
            self._fail_option = "Retry"

    def _draw_upgrading(self):
        y = self.display_class.titlebar_height + 2

        progress = sys_utils.get_upgrade_progress()
        phase = progress["phase"]
        pct = progress["percent"]
        done = progress["done"]
        total = progress["total"]
        unit = progress.get("unit", "bytes")

        if phase in ("failed", "unavailable", "connfail"):
            if phase == "unavailable":
                self._fail_reason = _("Version no\nlonger available")
            elif phase == "connfail":
                self._fail_reason = _("Can't reach\nupdate server")
            else:
                self._fail_reason = _("Update failed!")
            self._phase = "failed"
            self._fail_option = "Retry"
            return

        # Title
        if phase == "rebooting":
            label = _("Rebooting...")
        elif phase == "activating":
            label = _("Activating...")
        elif phase == "starting":
            label = _("Preparing...")
        else:
            label = _("Downloading...")

        self.draw.text(
            (0, y),
            label,
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        y += 20

        # Progress bar
        bar_x, bar_w, bar_h = 4, 120, 12
        # Background fill so bar is always visible
        self.draw.rectangle(
            [bar_x, y, bar_x + bar_w, y + bar_h],
            fill=self.colors.get(48),
            outline=self.colors.get(128),
        )
        fill_w = int(bar_w * pct / 100)
        if fill_w > 0:
            self.draw.rectangle(
                [bar_x + 1, y + 1, bar_x + fill_w, y + bar_h - 1],
                fill=self.colors.get(255),
            )

        # Percentage centered on bar
        pct_text = f"{pct}%"
        pct_bbox = self.fonts.base.font.getbbox(pct_text)
        pct_w = pct_bbox[2] - pct_bbox[0]
        pct_h = pct_bbox[3] - pct_bbox[1]
        pct_x = bar_x + (bar_w - pct_w) // 2
        pct_y = y + (bar_h - pct_h) // 2 - pct_bbox[1]
        self.draw.text(
            (pct_x, pct_y),
            pct_text,
            font=self.fonts.base.font,
            fill=self.colors.get(0) if pct > 45 else self.colors.get(192),
        )
        y += bar_h + 6

        # Amount below the bar: megabytes downloaded out of the total, or a
        # path count in the fallback case where byte sizes were unavailable.
        if phase == "downloading" and total > 0:
            if unit == "bytes":
                amount_text = f"{done / 1048576:.0f}/{total / 1048576:.0f} MB"
            else:
                amount_text = f"{done}/{total} paths"
            self.draw.text(
                (4, y),
                amount_text,
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            # Name the package currently being copied, if known.
            item = progress.get("item", "")
            if item:
                self.draw.text(
                    (4, y + 12),
                    item[:22],
                    font=self.fonts.base.font,
                    fill=self.colors.get(96),
                )


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
    Accepts markdown text directly via notes_text in item_definition.
    """

    __title__ = "NOTES"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._notes_text = self.item_definition.get("notes_text", "")
        self._loaded = False
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
            self._load_notes()

    def _load_notes(self):
        """Process notes text for display."""
        if self._notes_text:
            text = _strip_markdown(self._notes_text)
            self._text_layout.set_text(text)
            self._loaded = True
        else:
            self._loaded = True

    def update(self, force=False):
        self.clear_screen()
        draw_pos = self.display_class.titlebar_height + 2

        if not self._notes_text:
            self.draw.text(
                (10, draw_pos + 20),
                _("No release notes"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, draw_pos + 35),
                _("available"),
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
