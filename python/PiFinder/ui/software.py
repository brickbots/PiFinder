#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
UI modules for software updates, channel selection, and release notes.

Channels:
  - stable:   GitHub Releases (non-prerelease, >= MIN_NIXOS_VERSION)
  - beta:     GitHub Pre-releases (>= MIN_NIXOS_VERSION)
  - unstable: main branch + open PRs labeled 'testable'
"""

import logging
import re
from typing import Dict, List, Optional

import requests

from PiFinder import utils
from PiFinder.ui.base import UIModule
from PiFinder.ui.ui_utils import TextLayouter, TextLayouterScroll

sys_utils = utils.get_sys_utils()
logger = logging.getLogger("UISoftware")

GITHUB_REPO = "brickbots/PiFinder"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
GITHUB_PULLS_URL = f"https://api.github.com/repos/{GITHUB_REPO}/pulls"
GITHUB_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}"
MIN_NIXOS_VERSION = "2.5.0"
REQUEST_TIMEOUT = 10
_PR_VERSION_RE = re.compile(r"^PR#(\d+)-")


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


def _meets_min_version(version_str: str) -> bool:
    """Check if a version string is >= MIN_NIXOS_VERSION."""
    try:
        ver = _parse_version(version_str)
        minimum = _parse_version(MIN_NIXOS_VERSION)
        return ver >= minimum
    except Exception:
        return False


def _version_from_tag(tag: str) -> str:
    """Strip leading 'v' from a tag name to get the version string."""
    return tag.lstrip("v")


def _fetch_build_json(ref: str) -> Optional[dict]:
    """
    Fetch pifinder-build.json for a given git ref (sha or tag).
    Returns dict with 'store_path' and 'version', or None if unavailable.
    """
    url = f"{GITHUB_RAW_URL}/{ref}/pifinder-build.json"
    try:
        res = requests.get(url, timeout=REQUEST_TIMEOUT)
        if res.status_code == 200:
            data = res.json()
            if data.get("store_path"):
                return data
    except (requests.exceptions.RequestException, ValueError):
        pass
    return None


def _fetch_github_releases() -> tuple[list[dict], list[dict]]:
    """
    Fetch releases from GitHub API.
    Returns (stable_entries, beta_entries) sorted newest-first.
    Only includes entries that have a pifinder-build.json with a store path.
    """
    stable: list[dict] = []
    beta: list[dict] = []
    try:
        res = requests.get(
            GITHUB_RELEASES_URL,
            timeout=REQUEST_TIMEOUT,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        if res.status_code != 200:
            logger.warning("GitHub releases API returned %d", res.status_code)
            return stable, beta

        for release in res.json():
            if release.get("draft"):
                continue
            tag = release.get("tag_name", "")
            version = _version_from_tag(tag)
            if not _meets_min_version(version):
                continue

            build = _fetch_build_json(tag)
            if build is None:
                continue

            entry = {
                "label": tag,
                "ref": build["store_path"],
                "notes": release.get("body") or None,
                "version": build.get("version", version),
                "subtitle": release.get("name", tag),
            }

            if release.get("prerelease"):
                beta.append(entry)
            else:
                stable.append(entry)

    except requests.exceptions.RequestException as e:
        logger.warning("Could not fetch GitHub releases: %s", e)

    return stable, beta


def _fetch_testable_prs() -> list[dict]:
    """
    Fetch open PRs with the 'testable' label.
    Returns list of unstable entries (main branch prepended by caller).
    Only includes PRs that have a pifinder-build.json with a store path.
    """
    entries: list[dict] = []
    try:
        res = requests.get(
            GITHUB_PULLS_URL,
            params={"state": "open", "labels": "testable"},
            timeout=REQUEST_TIMEOUT,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        if res.status_code != 200:
            logger.warning("GitHub pulls API returned %d", res.status_code)
            return entries

        for pr in res.json():
            labels = [lbl.get("name", "") for lbl in pr.get("labels", [])]
            if "testable" not in labels:
                continue
            number = pr.get("number", 0)
            title = pr.get("title", "")
            sha = pr.get("head", {}).get("sha", "")
            body = pr.get("body") or None

            build = _fetch_build_json(sha)
            if build is None:
                continue

            short_sha = sha[:7]
            entries.append(
                {
                    "label": f"PR#{number}-{short_sha}",
                    "ref": build["store_path"],
                    "notes": body,
                    "version": build.get("version"),
                    "subtitle": title,
                }
            )

    except requests.exceptions.RequestException as e:
        logger.warning("Could not fetch testable PRs: %s", e)

    return entries


def _fetch_main_entry() -> Optional[dict]:
    """
    Fetch pifinder-build.json for the main branch.
    Returns an entry dict or None if unavailable.
    """
    build = _fetch_build_json("main")
    if build is None:
        return None
    return {
        "label": build.get("version") or "main",
        "ref": build["store_path"],
        "notes": None,
        "version": build.get("version"),
        "subtitle": "main branch",
    }


def _fetch_pr_title(pr_number: int) -> Optional[str]:
    """Fetch the title of a single PR by number."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_number}"
    try:
        res = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        if res.status_code == 200:
            return res.json().get("title")
    except requests.exceptions.RequestException:
        pass
    return None


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
        self._unstable_entries: List[dict] = []

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
        stable, beta = _fetch_github_releases()

        self._channels = {
            "stable": stable,
            "beta": beta,
        }

        if self.config_object.get_option("dev_mode", False):
            self._unstable_entries = self._fetch_unstable_entries()
            self._channels["unstable"] = self._unstable_entries

        # Try to find subtitle for current version from fetched entries
        self._software_subtitle = self._find_current_subtitle()

        self._channel_names = list(self._channels.keys())
        self._channel_index = 0
        self._refresh_version_list()
        self._phase = "browse"

    def _find_current_subtitle(self) -> Optional[str]:
        """Find a subtitle for the current version.

        Checks fetched channel entries first, then falls back to
        a direct PR title fetch for PR builds.
        """
        for entries in self._channels.values():
            for entry in entries:
                if entry.get("version") == self._software_version:
                    return entry.get("subtitle")

        m = _PR_VERSION_RE.match(self._software_version)
        if m:
            return _fetch_pr_title(int(m.group(1)))

        return None

    def _fetch_unstable_entries(self) -> list[dict]:
        unstable: list[dict] = []
        main_entry = _fetch_main_entry()
        if main_entry:
            unstable.append(main_entry)
        unstable.extend(_fetch_testable_prs())
        return unstable

    def _refresh_version_list(self):
        if not self._channel_names:
            self._version_list = []
            return
        channel = self._channel_names[self._channel_index]
        entries = self._channels.get(channel, [])
        self._version_list = [
            e for e in entries if e.get("version") != self._software_version
        ]
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
        self.draw.text(
            (10, y),
            _("Update failed!"),
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        y += 20
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

        if self._phase == "loading":
            if self._elipsis_count > 30:
                self._fetch_channels()
                # phase is now "browse", fall through
            else:
                self._draw_loading()
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
                self._phase = "confirm"
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
                self._confirm_options = ["Install"]
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

    # ------------------------------------------------------------------
    # Update action
    # ------------------------------------------------------------------

    def update_software(self):
        if not self._selected_version:
            return
        self._phase = "upgrading"
        self.clear_screen()
        self._draw_upgrading()
        self.screen_update()

        ref = self._selected_version.get("ref") or "release"
        if not sys_utils.update_software(ref=ref):
            self._phase = "failed"
            self._fail_option = "Retry"

    def _draw_upgrading(self):
        y = self.display_class.titlebar_height + 2

        progress = sys_utils.get_upgrade_progress()
        phase = progress["phase"]
        pct = progress["percent"]
        done = progress["done"]
        total = progress["total"]

        if phase == "failed":
            self._phase = "failed"
            self._fail_option = "Retry"
            return

        # Title
        if phase == "rebooting":
            label = _("Rebooting...")
        elif phase == "activating":
            label = _("Activating...")
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

        # Path count below bar
        if phase == "downloading" and total > 0:
            path_text = f"{done}/{total} paths"
            self.draw.text(
                (4, y),
                path_text,
                font=self.fonts.base.font,
                fill=self.colors.get(128),
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
