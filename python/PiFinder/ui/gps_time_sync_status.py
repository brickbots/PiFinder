#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
UI screen for time-source sync and helper status.
"""

import datetime
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from PiFinder.gps_time_sync import HELPER_STATUS_FILE, REQUEST_FILE, STATUS_FILE
from PiFinder.ui.base import UIModule
from PiFinder.ui.layout import rows_below_titlebar
from PiFinder.ui.ui_utils import TextLayouter

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


def _get(payload: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


class UIGPSTimeSyncStatus(UIModule):
    """Read-only time-sync status screen."""

    __title__ = "TIME SYNC"
    _display_mode_list = ["summary", "details"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.text_layout = TextLayouter(
            "",
            draw=self.draw,
            color=self.colors.get(255),
            colors=self.colors,
            font=self.fonts.base,
            available_lines=rows_below_titlebar(self.display_class, gap=1).max_visible,
        )
        self._last_display_mode = self.display_mode

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            with open(path, "r", encoding="utf-8") as file_in:
                payload = json.load(file_in)
        except FileNotFoundError:
            return None
        except Exception as exc:
            return {"state": "read_error", "message": str(exc)}
        return payload if isinstance(payload, dict) else {"state": "invalid_json"}

    def _format_bool(self, value: Any) -> str:
        if value is True:
            return _("Yes")
        if value is False:
            return _("No")
        return "--"

    def _format_age(self, seconds: Any) -> str:
        if not isinstance(seconds, (int, float)):
            return "--"
        if seconds < 60:
            return f"{seconds:.0f}s"
        if seconds < 3600:
            return f"{seconds / 60:.1f}m"
        return f"{seconds / 3600:.1f}h"

    def _format_offset(self, seconds: Any) -> str:
        if not isinstance(seconds, (int, float)):
            return "--"
        abs_seconds = abs(seconds)
        if abs_seconds >= 86400:
            return f"{seconds / 86400:.1f}d"
        if abs_seconds >= 1:
            return f"{seconds:.1f}s"
        return f"{seconds * 1000:.0f}ms"

    def _format_tacc(self, ns_value: Any) -> str:
        if not isinstance(ns_value, (int, float)) or ns_value < 0:
            return "--"
        if ns_value >= 1_000_000_000:
            return f"{ns_value / 1_000_000_000:.1f}s"
        if ns_value >= 1_000_000:
            return f"{ns_value / 1_000_000:.1f}ms"
        if ns_value >= 1_000:
            return f"{ns_value / 1_000:.1f}us"
        return f"{ns_value:.0f}ns"

    def _format_time(self, value: Any) -> str:
        if not isinstance(value, str) or not value:
            return "--"
        try:
            dt = datetime.datetime.fromisoformat(value)
        except ValueError:
            return value
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def _status_bundle(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
        status = self._read_json(STATUS_FILE)
        helper = _get(status, "helper")
        if not isinstance(helper, dict):
            helper = self._read_json(HELPER_STATUS_FILE)
        request_present = REQUEST_FILE.exists()
        return status, helper, request_present

    def _summary_lines(
        self,
        status: dict[str, Any] | None,
        helper: dict[str, Any] | None,
        request_present: bool,
    ) -> list[str]:
        if status is None:
            return [
                _("No time sync status"),
                _("Helper: {state}").format(
                    state=_get(helper, "state", default="--")
                ),
                _("Request: {present}").format(
                    present=_("Yes") if request_present else _("No")
                ),
                _("{square} Details").format(square=self._SQUARE_),
            ]

        latest = _get(status, "latest", default={})
        selected = _get(status, "selected", default={})
        ntp = _get(status, "ntp", default={})
        system_clock = _get(status, "system_clock_sync", default={})
        rtc = _get(status, "rtc_sync", default={})
        software_pps = _get(status, "software_pps", default={})

        source = _get(latest, "source", default="--")
        message_class = _get(latest, "message_class", default="")
        source_text = f"{source} {message_class}".strip()
        pps_text = (
            _("On {ticks}").format(ticks=_get(software_pps, "tick_count", default=0))
            if _get(software_pps, "enabled")
            else _("Off")
        )

        return [
            _("State: {state}").format(state=_get(status, "state", default="--")),
            _("Selected: {source}").format(
                source=_get(selected, "source", default="--")
            ),
            _("GPS valid: {valid}").format(
                valid=self._format_bool(_get(latest, "valid"))
            ),
            _("Source: {source}").format(source=source_text or "--"),
            _("NTP: {state}").format(state=_get(ntp, "state", default="--")),
            _("NTP srv: {server}").format(server=_get(ntp, "server", default="--")),
            _("tAcc: {tacc}").format(tacc=self._format_tacc(_get(latest, "tAcc_ns"))),
            _("Sys: {state}").format(
                state=_get(system_clock, "state", default="--")
            ),
            _("RTC: {state}").format(state=_get(rtc, "state", default="--")),
            _("Helper: {state}").format(state=_get(helper, "state", default="--")),
            _("Request: {present}").format(
                present=_("Yes") if request_present else _("No")
            ),
            _("PPS: {state}").format(state=pps_text),
            _("{square} Details").format(square=self._SQUARE_),
        ]

    def _detail_lines(
        self,
        status: dict[str, Any] | None,
        helper: dict[str, Any] | None,
        request_present: bool,
    ) -> list[str]:
        if status is None:
            return [
                _("Status file missing"),
                str(STATUS_FILE),
                _("Helper file: {state}").format(
                    state=_get(helper, "state", default="--")
                ),
                _("{square} Summary").format(square=self._SQUARE_),
            ]

        latest = _get(status, "latest", default={})
        selected = _get(status, "selected", default={})
        ntp = _get(status, "ntp", default={})
        samples = _get(status, "samples", default={})
        system_clock = _get(status, "system_clock_sync", default={})
        rtc = _get(status, "rtc_sync", default={})
        software_pps = _get(status, "software_pps", default={})
        helper_results = _get(helper, "results", default={})

        lines = [
            _("State: {state}").format(state=_get(status, "state", default="--")),
            _("Msg: {message}").format(message=_get(status, "message", default="--")),
            _("Selected: {source}").format(
                source=_get(selected, "source", default="--")
            ),
            _("Sel time: {time}").format(
                time=self._format_time(_get(selected, "time"))
            ),
            _("GPS: {time}").format(
                time=self._format_time(_get(latest, "gps_time"))
            ),
            _("Age: {age}").format(age=self._format_age(_get(latest, "age_seconds"))),
            _("Valid: {valid}").format(valid=self._format_bool(_get(latest, "valid"))),
            _("tAcc: {tacc}").format(tacc=self._format_tacc(_get(latest, "tAcc_ns"))),
            _("Offset: {offset}").format(
                offset=self._format_offset(_get(latest, "offset_seconds"))
            ),
            _("Sys off: {offset}").format(
                offset=self._format_offset(_get(latest, "system_offset_seconds"))
            ),
            _("NTP: {state}").format(state=_get(ntp, "state", default="--")),
            _("NTP srv: {server}").format(server=_get(ntp, "server", default="--")),
            _("NTP time: {time}").format(
                time=self._format_time(_get(ntp, "time"))
            ),
            _("NTP delay: {delay}").format(
                delay=self._format_offset(_get(ntp, "delay_seconds"))
            ),
            _("Samples: {count}/{min_required}").format(
                count=_get(samples, "count", default=0),
                min_required=_get(samples, "min_required", default="--"),
            ),
            _("Sys req: {state}").format(
                state=_get(system_clock, "state", default="--")
            ),
            _("RTC req: {state}").format(state=_get(rtc, "state", default="--")),
            _("PPS ticks: {ticks}").format(
                ticks=_get(software_pps, "tick_count", default=0)
            ),
            _("Helper: {state}").format(state=_get(helper, "state", default="--")),
            _("Helper UID: {uid}").format(
                uid=_get(helper, "effective_uid", default="--")
            ),
            _("Helper msg: {message}").format(
                message=_get(helper, "message", default="--")
            ),
            _("Req file: {present}").format(
                present=_("Yes") if request_present else _("No")
            ),
        ]

        if isinstance(helper_results, dict):
            if "system_clock" in helper_results:
                lines.append(
                    _("Sys result: {state}").format(
                        state=_get(helper_results, "system_clock", "state", default="--")
                    )
                )
            if "rtc" in helper_results:
                lines.append(
                    _("RTC result: {state}").format(
                        state=_get(helper_results, "rtc", "state", default="--")
                    )
                )

        lines.append(_("{square} Summary").format(square=self._SQUARE_))
        return lines

    def update(self, force=False):
        status, helper, request_present = self._status_bundle()
        self.clear_screen()
        if self.display_mode == "summary":
            lines = self._summary_lines(status, helper, request_present)
        else:
            lines = self._detail_lines(status, helper, request_present)

        reset_pointer = self.display_mode != self._last_display_mode
        self._last_display_mode = self.display_mode
        self.text_layout.set_text("\n".join(lines), reset_pointer=reset_pointer)
        self.text_layout.draw(pos=(0, self.display_class.titlebar_height))
        return self.screen_update()

    def key_up(self):
        self.text_layout.previous()
        self.update()

    def key_down(self):
        self.text_layout.next()
        self.update()
