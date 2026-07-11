"""Network policy daemon: wired -> wifi client -> access point.

Event-driven via NetworkManager's GObject API (libnm) — the same API
sys_utils uses — plus a slow tick for the time-based rules. Replaces the
nmcli-parsing shell fallback, whose "wifi connected" check matched the AP
itself, so once the AP was up nothing ever retried the client network.

The decision logic lives in net_policy_core (pure, unit-tested); this module
only observes NetworkManager and executes the returned actions.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import gi

gi.require_version("NM", "1.0")
from gi.repository import GLib, NM  # noqa: E402

from PiFinder.net_policy_core import (  # noqa: E402
    AP_DOWN,
    AP_UP,
    PolicyState,
    Snapshot,
    decide,
)

logger = logging.getLogger("NetPolicy")

AP_CONNECTION_NAME = "PiFinder-AP"
WIFI_MODE_FILE = (
    Path(os.environ.get("PIFINDER_DATA", "/home/pifinder/PiFinder_data")) / "wifi_mode"
)

# Safety-net re-evaluation cadence; NM signals are the primary trigger.
TICK_SECONDS = 10
# Collapse bursts of NM signals into one evaluation.
DEBOUNCE_SECONDS = 2


def _read_forced_ap() -> bool:
    try:
        return WIFI_MODE_FILE.read_text().strip() == "AP"
    except OSError:
        return False


def _count_ap_stations(iface: str) -> int:
    """Associated stations on the AP interface, via `iw` (libnm has no API
    for AP client lists). Errs toward "occupied" so a counting failure never
    causes the retry logic to yank a possibly-used AP."""
    try:
        out = subprocess.run(
            ["iw", "dev", iface, "station", "dump"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return 1
    return sum(1 for line in out.splitlines() if line.startswith("Station"))


class NetPolicyDaemon:
    def __init__(self) -> None:
        self._client = NM.Client.new(None)
        self._state = PolicyState()
        self._debounce_id: Optional[int] = None

        self._client.connect("notify::active-connections", self._on_change)
        self._client.connect("device-added", self._on_device_added)
        self._client.connect("device-removed", self._on_change)
        for dev in self._client.get_devices():
            self._hook_device(dev)

        GLib.timeout_add_seconds(TICK_SECONDS, self._on_tick)
        self._evaluate()

    # -- NM signal plumbing --------------------------------------------------

    def _hook_device(self, dev: NM.Device) -> None:
        dev.connect("state-changed", self._on_change)

    def _on_device_added(self, _client, dev) -> None:
        self._hook_device(dev)
        self._schedule_evaluate()

    def _on_change(self, *_args) -> None:
        self._schedule_evaluate()

    def _on_tick(self) -> bool:
        self._evaluate()
        return True  # keep the tick alive

    def _schedule_evaluate(self) -> None:
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add_seconds(
            DEBOUNCE_SECONDS, self._debounced_evaluate
        )

    def _debounced_evaluate(self) -> bool:
        self._debounce_id = None
        self._evaluate()
        return False  # one-shot

    # -- state observation ---------------------------------------------------

    def _wifi_iface(self) -> Optional[str]:
        for dev in self._client.get_devices():
            if dev.get_device_type() == NM.DeviceType.WIFI:
                return dev.get_iface()
        return None

    def _snapshot(self) -> Snapshot:
        eth_connected = False
        wifi_client_active = False
        ap_active = False

        for ac in self._client.get_active_connections():
            if ac.get_state() != NM.ActiveConnectionState.ACTIVATED:
                continue
            conn_type = ac.get_connection_type()
            if conn_type == "802-3-ethernet":
                eth_connected = True
            elif conn_type == "802-11-wireless":
                if ac.get_id() == AP_CONNECTION_NAME:
                    ap_active = True
                else:
                    wifi_client_active = True

        ap_stations = 0
        if ap_active:
            iface = self._wifi_iface()
            ap_stations = _count_ap_stations(iface) if iface else 1

        return Snapshot(
            forced_ap=_read_forced_ap(),
            eth_connected=eth_connected,
            wifi_client_active=wifi_client_active,
            ap_active=ap_active,
            ap_stations=ap_stations,
        )

    # -- actions ---------------------------------------------------------------

    def _evaluate(self) -> None:
        snap = self._snapshot()
        action = decide(snap, self._state, time.monotonic())
        if action == AP_UP:
            logger.info("no connectivity after grace period — bringing AP up")
            self._ap_up()
        elif action == AP_DOWN:
            reason = (
                "wired connectivity present"
                if snap.eth_connected
                else ("idle AP — retrying client network")
            )
            logger.info("%s — bringing AP down", reason)
            self._ap_down()

    def _ap_up(self) -> None:
        conn = None
        for c in self._client.get_connections():
            if c.get_id() == AP_CONNECTION_NAME:
                conn = c
                break
        if conn is None:
            logger.error("AP connection %r not found", AP_CONNECTION_NAME)
            return
        self._client.activate_connection_async(
            conn, None, None, None, self._on_action_done, "activate"
        )

    def _ap_down(self) -> None:
        for ac in self._client.get_active_connections():
            if ac.get_id() == AP_CONNECTION_NAME:
                self._client.deactivate_connection_async(
                    ac, None, self._on_action_done, "deactivate"
                )
                return

    def _on_action_done(self, client, result, verb) -> None:
        try:
            if verb == "activate":
                client.activate_connection_finish(result)
            else:
                client.deactivate_connection_finish(result)
        except GLib.Error as e:
            logger.warning("AP %s failed: %s", verb, e.message)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    NetPolicyDaemon()
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
