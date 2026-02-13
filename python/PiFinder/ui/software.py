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
import time
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

            short_title = title[:20] + "..." if len(title) > 20 else title
            entries.append(
                {
                    "label": f"PR#{number} {short_title}",
                    "ref": build["store_path"],
                    "notes": body,
                    "version": build.get("version"),
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
        "label": "main",
        "ref": build["store_path"],
        "notes": None,
        "version": build.get("version"),
    }


class UISoftware(UIModule):
    """
    Software update UI.

    Phases:
      loading  - animated "Checking for updates..."
      browse   - header (version + channel selector) + scrollable version list
      confirm  - selected version details + Install / Notes / Cancel
      failed   - update failed + Retry / Cancel
    """

    __title__ = "SOFTWARE"
    MAX_VISIBLE = 5

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
        with open(self.wifi_txt, "r") as f:
            self._wifi_mode = f.read().strip()
        self._software_version = utils.get_version()

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
        self._unstable_unlocked = False
        self._unstable_entries: List[dict] = []
        self._square_count = 0

        self._scroll_label: Optional[TextLayouterScroll] = None
        self._scroll_label_text: Optional[str] = None

    def active(self):
        super().active()
        self._phase = "loading"
        self._elipsis_count = 0
        self._focus = "channel"
        self._channel_index = 0
        self._list_index = 0
        self._scroll_offset = 0
        self._selected_version = None

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _fetch_channels(self):
        stable, beta = _fetch_github_releases()
        pr_entries = _fetch_testable_prs()

        unstable = []
        main_entry = _fetch_main_entry()
        if main_entry:
            unstable.append(main_entry)
        unstable.extend(pr_entries)

        self._channels = {
            "stable": stable,
            "beta": beta,
        }
        self._unstable_entries = unstable

        if self._unstable_unlocked:
            self._channels["unstable"] = unstable

        self._channel_names = list(self._channels.keys())
        self._channel_index = 0
        self._refresh_version_list()
        self._phase = "browse"

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
        self._scroll_label = None
        self._scroll_label_text = None

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_separator(self, y):
        self.draw.line([(0, y), (127, y)], fill=self.colors.get(64))

    def _draw_loading(self):
        y = self.display_class.titlebar_height + 2
        self.draw.text(
            (0, y),
            self._software_version,
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
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
        self.draw.text(
            (0, y),
            self._software_version,
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
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
        self.draw.text(
            (0, y),
            self._software_version,
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        y += 14

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

        visible = min(self.MAX_VISIBLE, len(self._version_list))
        # available width after arrow (10px) in characters
        label_width = self.fonts.base.line_length - 2
        for i in range(visible):
            idx = self._scroll_offset + i
            if idx >= len(self._version_list):
                break
            entry = self._version_list[idx]
            item_y = y + i * 12
            label = entry["label"]

            if self._focus == "list" and idx == self._list_index:
                self.draw.text(
                    (0, item_y),
                    self._RIGHT_ARROW,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )
                if self._scroll_label_text != label:
                    self._scroll_label = TextLayouterScroll(
                        label,
                        draw=self.draw,
                        color=self.colors.get(255),
                        font=self.fonts.bold,
                        width=label_width,
                    )
                    self._scroll_label_text = label
                self._scroll_label.draw((10, item_y))
            else:
                self.draw.text(
                    (10, item_y),
                    label[:label_width],
                    font=self.fonts.base.font,
                    fill=self.colors.get(192),
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

        version_label = (
            self._selected_version.get("version") or self._selected_version["label"]
        )
        self.draw.text(
            (0, y),
            version_label,
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
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
        time.sleep(1 / 30)
        self.clear_screen()

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

    def _reset_unlock(self):
        self._square_count = 0

    def key_up(self):
        self._reset_unlock()
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
        self._reset_unlock()
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
        self._reset_unlock()
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
        self._reset_unlock()
        if self._phase == "confirm":
            self._phase = "browse"
            return False
        return True

    def key_square(self):
        self._square_count += 1
        if self._square_count >= 7 and not self._unstable_unlocked:
            self._unstable_unlocked = True
            self._channels["unstable"] = self._unstable_entries
            self._channel_names = list(self._channels.keys())
            self.message(_("Unstable\nunlocked"), 1)

    def key_number(self, number):
        self._square_count = 0

    # ------------------------------------------------------------------
    # Update action
    # ------------------------------------------------------------------

    def update_software(self):
        if not self._selected_version:
            return
        ref = self._selected_version.get("ref") or "release"
        self.message(_("Updating..."), 10)
        if sys_utils.update_software(ref=ref):
            self.message(_("Ok! Restarting..."), 10)
            sys_utils.restart_system()
        else:
            self._phase = "failed"
            self._fail_option = "Retry"


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
        time.sleep(1 / 30)
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
