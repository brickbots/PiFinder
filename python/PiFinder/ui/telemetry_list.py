"""
UI screen for listing and loading telemetry recording sessions.

Lists .jsonl files from ~/PiFinder_data/telemetry/ with filename and size.
Selecting a file triggers replay via the integrator command queue.
"""

import logging

from PiFinder.ui.text_menu import UITextMenu
from PiFinder.telemetry import TELEMETRY_DIR

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


logger = logging.getLogger("UI.TelemetryList")


class UITelemetryList(UITextMenu):
    """File picker for telemetry sessions."""

    __title__ = "Telemetry"

    def __init__(self, *args, **kwargs):
        self._sessions = self._scan_sessions()
        kwargs["item_definition"] = self._create_menu_definition()
        super().__init__(*args, **kwargs)

    def _scan_sessions(self):
        """Scan telemetry directory for session files."""
        sessions = []
        if not TELEMETRY_DIR.exists():
            return sessions

        # Look for session dirs (contain session.jsonl) and standalone .jsonl files
        for entry in sorted(TELEMETRY_DIR.iterdir(), reverse=True):
            jsonl_path = None
            if entry.is_dir():
                candidate = entry / "session.jsonl"
                if candidate.exists():
                    jsonl_path = candidate
            elif entry.suffix == ".jsonl":
                jsonl_path = entry

            if jsonl_path:
                size_kb = jsonl_path.stat().st_size / 1024
                label = entry.name
                if size_kb >= 1024:
                    size_str = f"{size_kb / 1024:.1f}MB"
                else:
                    size_str = f"{size_kb:.0f}KB"
                sessions.append(
                    {
                        "label": label,
                        "size_str": size_str,
                        "path": str(entry),
                    }
                )
        return sessions

    def _create_menu_definition(self):
        items = []
        for s in self._sessions:
            items.append(
                {
                    "name": f"{s['label']} ({s['size_str']})",
                    "value": s["path"],
                }
            )
        if not items:
            items.append({"name": "No sessions found", "value": None})
        return {"name": "Telemetry", "select": "single", "items": items}

    def key_right(self):
        """Select a session to replay."""
        if not self._sessions:
            self.message("No sessions", 2)
            return False

        idx = self._current_item_index
        items = self.item_definition["items"]
        if idx >= len(items):
            return False

        session_path = items[idx].get("value")
        if session_path is None:
            return False

        # Send replay command to integrator
        if "integrator" in self.command_queues:
            self.command_queues["camera"].put("stop")
            self.command_queues["integrator"].put(("replay", session_path))
            self.message("Replay\nstarted", 2)
            logger.info("Starting telemetry replay: %s", session_path)
        else:
            self.message("No integrator\nqueue", 2)
            logger.warning("Integrator command queue not available")

        return True
