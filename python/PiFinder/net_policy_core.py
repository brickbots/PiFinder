"""Decision core for the PiFinder network policy daemon.

Pure logic with no NetworkManager dependency, so it is unit-testable on any
machine. The daemon (net_policy.py) feeds it snapshots of the current network
state and executes the actions it returns.

Connectivity priority: wired -> wifi client -> access point. The AP is a
fallback for reaching an otherwise-offline device, never a preference: with a
cable plugged in or a client network joined, the AP stays down.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# How long NetworkManager gets to join a known client network before the AP
# comes up. Also applies after an idle-AP retry drops the AP.
GRACE_SECONDS = 45

# While the AP is up with nobody connected to it, drop it this often so NM can
# rescan and rejoin a client network that has come into range. Without this
# the AP is sticky: an active AP counts as "wifi connected", so nothing ever
# retries the client network.
CLIENT_RETRY_SECONDS = 300

AP_UP = "ap_up"
AP_DOWN = "ap_down"


@dataclass
class Snapshot:
    """Point-in-time network state, as observed by the daemon."""

    forced_ap: bool  # operator forced AP mode via PiFinder_data/wifi_mode
    eth_connected: bool  # an ethernet connection is activated
    wifi_client_active: bool  # a non-AP wifi connection is activated
    ap_active: bool  # the PiFinder-AP connection is activated
    ap_stations: int  # clients associated to the AP (0 when ap inactive)


@dataclass
class PolicyState:
    """Timing state carried between decisions."""

    disconnected_since: Optional[float] = None
    last_client_retry: Optional[float] = None


def decide(snap: Snapshot, state: PolicyState, now: float) -> Optional[str]:
    """Return the action to take (AP_UP / AP_DOWN / None), updating `state`.

    `now` is a monotonic timestamp supplied by the caller.
    """
    if snap.forced_ap:
        state.disconnected_since = None
        return None if snap.ap_active else AP_UP

    if snap.eth_connected:
        # Wired connectivity is sufficient: the device is reachable and
        # online. Dropping the AP frees the radio so NM autoconnects to a
        # client network whenever one appears.
        state.disconnected_since = None
        return AP_DOWN if snap.ap_active else None

    if snap.wifi_client_active:
        state.disconnected_since = None
        return None

    if snap.ap_active:
        # Offline fallback is serving. Periodically drop an *idle* AP so NM
        # can retry the client network; the grace path below restores the AP
        # if nothing joins. Never yanks the AP away from a connected user.
        if state.last_client_retry is None:
            state.last_client_retry = now
            return None
        if (
            snap.ap_stations == 0
            and now - state.last_client_retry >= CLIENT_RETRY_SECONDS
        ):
            state.last_client_retry = now
            state.disconnected_since = now
            return AP_DOWN
        return None

    # Fully disconnected: give NM a grace period to join a known client
    # network, then bring up the AP.
    if state.disconnected_since is None:
        state.disconnected_since = now
        return None
    if now - state.disconnected_since >= GRACE_SECONDS:
        state.disconnected_since = None
        state.last_client_retry = now
        return AP_UP
    return None
