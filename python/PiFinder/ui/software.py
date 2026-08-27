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
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

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

# Last successfully fetched manifest, kept on disk so the screen can render a
# version list immediately on entry while a fresh copy is fetched in the
# background.
MANIFEST_CACHE_PATH = utils.data_dir / "update_manifest.json"

# A trunk entry is only offered when the branch it tracks is actually a NixOS
# branch — detected by this file existing in the branch's tree. Keeps a
# non-NixOS upstream main from showing up as an installable build.
NIXOS_MARKER_FILE = "flake.nix"


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
        "title": title,
        "channel": channel,
        "kind": item.get("kind"),
        "number": item.get("number"),
        "built_at": item.get("built_at"),
        "source_ref": item.get("source_ref"),
        "source_sha": item.get("source_sha"),
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


def _fetch_raw_manifest() -> dict:
    """
    Fetch CI-generated update metadata as the raw manifest document.
    Raises RequestException for network failures so the caller can show offline.
    """
    res = requests.get(UPDATE_MANIFEST_URL, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    manifest = res.json()
    if manifest.get("schema") != 1:
        raise ValueError("unsupported update manifest schema")
    if not isinstance(manifest.get("channels", {}), dict):
        raise ValueError("invalid update manifest channels")
    return manifest


def _parse_manifest(manifest: dict) -> dict[str, list[dict]]:
    """Convert a raw manifest document into per-channel UI entries.

    Trunk entries whose branch is known to lack the NixOS marker file are
    dropped (annotation left by _annotate_trunk_entries; unknown means keep).
    """
    channels: dict[str, list[dict]] = {}
    manifest_channels = manifest.get("channels", {})
    if not isinstance(manifest_channels, dict):
        manifest_channels = {}

    for channel in ("stable", "beta", "unstable"):
        entries: list[dict] = []
        raw_entries = manifest_channels.get(channel, [])
        if not isinstance(raw_entries, list):
            continue
        for item in raw_entries:
            if not isinstance(item, dict):
                continue
            if item.get("kind") == "trunk" and item.get("nixos_branch") is False:
                continue
            entry = _entry_from_manifest(item, channel)
            if entry is not None:
                entries.append(entry)
        channels[channel] = entries

    return channels


def _fetch_update_manifest() -> dict[str, list[dict]]:
    """Fetch and parse update metadata in one step (no cache involvement)."""
    return _parse_manifest(_fetch_raw_manifest())


def _load_cached_manifest() -> Optional[dict]:
    """Return the last cached raw manifest, or None when absent/invalid."""
    try:
        with open(MANIFEST_CACHE_PATH) as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        return None
    return manifest


def _save_cached_manifest(manifest: dict) -> None:
    """Best-effort atomic write of the manifest cache."""
    try:
        MANIFEST_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = MANIFEST_CACHE_PATH.with_suffix(".json.tmp")
        with open(tmp_path, "w") as f:
            json.dump(manifest, f)
        tmp_path.replace(MANIFEST_CACHE_PATH)
    except OSError as e:
        logger.warning("Could not cache update manifest: %s", e)


def _branch_has_nixos_marker(source_repo: str, source_ref: str) -> Optional[bool]:
    """Whether the branch's tree contains the NixOS marker file.

    Returns None when the check is inconclusive (network trouble, unexpected
    status) so callers can keep the entry rather than hide a real build.
    """
    url = (
        f"https://raw.githubusercontent.com/{source_repo}/"
        f"{source_ref}/{NIXOS_MARKER_FILE}"
    )
    try:
        res = requests.head(url, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException:
        return None
    if res.status_code == 200:
        return True
    if res.status_code == 404:
        return False
    return None


def _annotate_trunk_entries(manifest: dict) -> None:
    """Stamp nixos_branch on trunk entries in a raw manifest (in place).

    An inconclusive check leaves the entry unannotated, and unannotated trunk
    entries stay visible — a flaky network must not hide a real build. The
    annotation is persisted with the cache, so the cached list applies the
    same verdict without re-checking.
    """
    channels = manifest.get("channels", {})
    if not isinstance(channels, dict):
        return
    unstable = channels.get("unstable", [])
    if not isinstance(unstable, list):
        return
    for item in unstable:
        if not isinstance(item, dict) or item.get("kind") != "trunk":
            continue
        repo = item.get("source_repo")
        ref = item.get("source_ref")
        if not repo or not ref:
            continue
        marker = _branch_has_nixos_marker(repo, ref)
        if marker is not None:
            item["nixos_branch"] = marker


def _format_age(built_at: Optional[str]) -> Optional[str]:
    """Human-readable age of a build timestamp ("5m ago", "3h ago", "2d ago")."""
    if not built_at:
        return None
    try:
        built = datetime.fromisoformat(built_at)
    except ValueError:
        return None
    if built.tzinfo is None:
        built = built.replace(tzinfo=timezone.utc)
    minutes = max(0, int((datetime.now(timezone.utc) - built).total_seconds() // 60))
    if minutes < 60:
        return _("{minutes}m ago").format(minutes=minutes)
    hours = minutes // 60
    if hours < 24:
        return _("{hours}h ago").format(hours=hours)
    return _("{days}d ago").format(days=hours // 24)


def _entry_row_parts(entry: dict) -> Tuple[str, str]:
    """Split a version row into a fixed prefix and the scrollable text.

    PR rows lead with the bare PR number, trunk rows with a dot; the store
    hash never appears in the list — titles/branch names are what a human
    scans for.
    """
    if entry.get("kind") == "pr" and entry.get("number"):
        return f"{entry['number']} ", entry.get("title") or entry["label"]
    if entry.get("is_trunk"):
        return "• ", entry.get("source_ref") or entry["label"]
    return "", entry["label"]


def _entry_detail(entry: dict) -> str:
    """Second line of a focused version row: unavailability beats build info.

    Build info is age plus the short commit hash ("built 5h ago · 2692406") —
    the hash stays out of the list rows but remains one focus away.
    """
    if entry.get("unavailable"):
        return entry.get("subtitle", "")
    parts = []
    age = _format_age(entry.get("built_at"))
    if age:
        parts.append(_("built {age}").format(age=age))
    sha = entry.get("source_sha")
    if isinstance(sha, str) and sha:
        parts.append(sha[:7])
    if parts:
        return " · ".join(parts)
    return entry.get("subtitle", "")


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

        # Background manifest refresh: the worker thread writes a single
        # ("ok", channels) / ("error", None) tuple; update() consumes it.
        self._refresh_thread: Optional[threading.Thread] = None
        self._refresh_result: Optional[Tuple[str, Optional[Dict[str, List[dict]]]]] = (
            None
        )
        self._checking = False
        self._check_failed = False

        self._scrollers: Dict[str, TextLayouterScroll] = {}
        self._scroller_phase: Optional[str] = None
        self._scroller_index: Optional[int] = None

    def active(self):
        super().active()
        self._elipsis_count = 0
        self._focus = "channel"
        self._channel_index = 0
        self._list_index = 0
        self._scroll_offset = 0
        self._selected_version = None
        self._scrollers = {}
        self._scroller_phase = None
        self._scroller_index = None
        self._check_failed = False

        # Render the last cached manifest immediately; a fresh copy is fetched
        # in the background and swapped in when it lands.
        cached = _load_cached_manifest()
        if cached is not None:
            self._apply_manifest(_parse_manifest(cached))
            self._phase = "browse"
        else:
            self._phase = "loading"
        self._start_refresh()

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _list_rollback_targets(self) -> List[dict]:
        # Rollback targets come from local, immutable generation data, so they
        # are available even when the manifest can't be fetched — which is
        # exactly when rollback matters most. Entries are validated like
        # manifest entries: anything without a string label can't be rendered
        # or installed, so it is dropped rather than crash the screen.
        try:
            targets = sys_utils.list_rollback_targets()
            return [
                t
                for t in targets
                if isinstance(t, dict) and isinstance(t.get("label"), str)
            ]
        except Exception as e:  # never let rollback listing break the screen
            logger.warning("Could not list rollback targets: %s", e)
            return []

    def _start_refresh(self):
        if self._refresh_thread is not None and self._refresh_thread.is_alive():
            return
        self._checking = True
        self._refresh_result = None
        self._refresh_thread = threading.Thread(
            target=self._refresh_worker, daemon=True
        )
        self._refresh_thread.start()

    def _refresh_worker(self):
        """Background thread: fetch the manifest, annotate, cache, parse."""
        try:
            manifest = _fetch_raw_manifest()
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.warning("Software update check failed (offline/invalid?): %s", e)
            self._refresh_result = ("error", None)
            return
        _annotate_trunk_entries(manifest)
        _save_cached_manifest(manifest)
        self._refresh_result = ("ok", _parse_manifest(manifest))

    def _consume_refresh_result(self):
        """Apply a finished background refresh, if any (main thread only)."""
        result = self._refresh_result
        if result is None:
            return
        self._refresh_result = None
        self._checking = False
        status, manifest_channels = result

        if status == "ok" and manifest_channels is not None:
            self._check_failed = False
            self._apply_manifest(manifest_channels, keep_position=True)
            if self._phase in ("loading", "offline"):
                self._phase = "browse"
            return

        # Refresh failed. With a cached list on screen just flag it; without
        # one fall back to rollback-only browse, or the offline notice.
        if self._phase != "loading":
            self._check_failed = True
            return
        rollback = self._list_rollback_targets()
        if rollback:
            self._check_failed = True
            self._manifest_channels = {}
            self._channels = {"rollback": rollback}
            self._channel_names = list(self._channels.keys())
            self._channel_index = 0
            self._refresh_version_list()
            self._phase = "browse"
        else:
            self._phase = "offline"

    def _apply_manifest(
        self, manifest_channels: Dict[str, List[dict]], keep_position: bool = False
    ):
        self._manifest_channels = manifest_channels
        self._channels = {
            "stable": manifest_channels.get("stable", []),
            "beta": manifest_channels.get("beta", []),
        }

        if self.config_object.get_option("dev_mode", False):
            self._unstable_entries = manifest_channels.get("unstable", [])
            self._channels["unstable"] = self._unstable_entries

        rollback = self._list_rollback_targets()
        if rollback:
            self._channels["rollback"] = rollback

        # Try to find subtitle for current version from fetched entries
        self._software_subtitle = self._find_current_subtitle()

        # A background refresh should not yank the user's channel selection.
        prev_channel = (
            self._channel_names[self._channel_index] if self._channel_names else None
        )
        self._channel_names = list(self._channels.keys())
        if keep_position and prev_channel in self._channel_names:
            self._channel_index = self._channel_names.index(prev_channel)
        else:
            self._channel_index = 0
        self._refresh_version_list(keep_position=keep_position)

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

    def _refresh_version_list(self, keep_position: bool = False):
        if not self._channel_names:
            self._version_list = []
            return
        channel = self._channel_names[self._channel_index]
        entries = self._channels.get(channel, [])
        if channel == "rollback":
            self._version_list = entries
        else:
            self._version_list = _hide_current_build(entries, _current_store_path())
        if keep_position and self._version_list:
            self._list_index = min(self._list_index, len(self._version_list) - 1)
            self._scroll_offset = min(self._scroll_offset, self._list_index)
        else:
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
            self._draw_refresh_status()
            return

        label_width = self.fonts.base.line_length - 2
        list_bottom = 114 if (self._checking or self._check_failed) else 128
        current_y = y
        for i in range(len(self._version_list)):
            idx = self._scroll_offset + i
            if idx >= len(self._version_list):
                break
            entry = self._version_list[idx]
            prefix, text = _entry_row_parts(entry)

            if self._focus == "list" and idx == self._list_index:
                if current_y + 24 > list_bottom:
                    break
                self.draw.text(
                    (0, current_y),
                    self._RIGHT_ARROW,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )
                # The prefix (PR number / trunk dot) stays fixed; only the
                # title scrolls after it.
                text_x = 10
                scroll_width = label_width
                if prefix:
                    self.draw.text(
                        (text_x, current_y),
                        prefix,
                        font=self.fonts.bold.font,
                        fill=self.colors.get(255),
                    )
                    text_x += int(self.fonts.bold.width * len(prefix))
                    scroll_width = max(1, label_width - len(prefix))
                scroller = self._get_scroller(
                    "browse_label",
                    text,
                    self.fonts.bold,
                    self.colors.get(255),
                    scroll_width,
                )
                scroller.draw((text_x, current_y))
                current_y += 12
                detail = _entry_detail(entry)
                if detail:
                    sub_scroller = self._get_scroller(
                        "browse_sub",
                        detail,
                        self.fonts.base,
                        self.colors.get(255),
                        label_width,
                    )
                    sub_scroller.draw((10, current_y))
                current_y += 12
            else:
                # Unfocused rows stay dim so the selected row and its detail
                # line carry the visual weight.
                if current_y + 12 > list_bottom:
                    break
                # The trunk ("main") row stands out from the PR rows: bold and
                # brighter, with a leading dot.
                if entry.get("is_trunk"):
                    self.draw.text(
                        (10, current_y),
                        f"{prefix}{text}"[:label_width],
                        font=self.fonts.bold.font,
                        fill=self.colors.get(192),
                    )
                else:
                    self.draw.text(
                        (10, current_y),
                        f"{prefix}{text}"[:label_width],
                        font=self.fonts.base.font,
                        fill=self.colors.get(128),
                    )
                current_y += 12

        self._draw_refresh_status()

    def _draw_refresh_status(self):
        """Bottom-line indicator for the background manifest refresh."""
        if self._checking:
            dots = "." * ((self._elipsis_count // 10) % 4)
            text = _("checking for updates") + dots
            self._elipsis_count += 1
            if self._elipsis_count > 39:
                self._elipsis_count = 0
        elif self._check_failed:
            text = _("update check failed")
        else:
            return
        self.draw.text(
            (4, 115),
            text,
            font=self.fonts.base.font,
            fill=self.colors.get(96),
        )

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

        age = _format_age(self._selected_version.get("built_at"))
        if age:
            self.draw.text(
                (0, y),
                _("built {age}").format(age=age),
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            y += 11

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

        self._consume_refresh_result()

        if self._phase == "loading":
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
        # Manual refresh: re-fetch the manifest with the same feedback as the
        # automatic check on entry — the bottom status line in browse, the
        # full "Checking for updates" screen when currently offline.
        if self._phase == "browse":
            self._start_refresh()
        elif self._phase == "offline":
            self._phase = "loading"
            self._elipsis_count = 0
            self._start_refresh()

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
