import pytest

from PiFinder.net_policy_core import (
    AP_DOWN,
    AP_UP,
    CLIENT_RETRY_SECONDS,
    GRACE_SECONDS,
    PolicyState,
    Snapshot,
    decide,
)


def _snap(**overrides):
    snap = Snapshot(
        forced_ap=False,
        eth_connected=False,
        wifi_client_active=False,
        ap_active=False,
        ap_stations=0,
    )
    for key, value in overrides.items():
        setattr(snap, key, value)
    return snap


@pytest.mark.unit
class TestForcedAp:
    def test_brings_ap_up(self):
        assert decide(_snap(forced_ap=True), PolicyState(), 100.0) == AP_UP

    def test_noop_when_already_up(self):
        snap = _snap(forced_ap=True, ap_active=True)
        assert decide(snap, PolicyState(), 100.0) is None

    def test_forced_ap_wins_over_ethernet(self):
        snap = _snap(forced_ap=True, eth_connected=True, ap_active=True)
        assert decide(snap, PolicyState(), 100.0) is None


@pytest.mark.unit
class TestWiredPriority:
    def test_ap_dropped_when_wired(self):
        snap = _snap(eth_connected=True, ap_active=True)
        assert decide(snap, PolicyState(), 100.0) == AP_DOWN

    def test_noop_when_wired_and_no_ap(self):
        assert decide(_snap(eth_connected=True), PolicyState(), 100.0) is None

    def test_wired_resets_grace_timer(self):
        state = PolicyState(disconnected_since=50.0)
        decide(_snap(eth_connected=True), state, 100.0)
        assert state.disconnected_since is None


@pytest.mark.unit
class TestWifiClient:
    def test_noop_when_client_connected(self):
        snap = _snap(wifi_client_active=True)
        assert decide(snap, PolicyState(), 100.0) is None

    def test_client_resets_grace_timer(self):
        state = PolicyState(disconnected_since=50.0)
        decide(_snap(wifi_client_active=True), state, 100.0)
        assert state.disconnected_since is None


@pytest.mark.unit
class TestGraceFallback:
    def test_no_immediate_ap(self):
        state = PolicyState()
        assert decide(_snap(), state, 100.0) is None
        assert state.disconnected_since == 100.0

    def test_ap_up_after_grace(self):
        state = PolicyState()
        decide(_snap(), state, 100.0)
        assert decide(_snap(), state, 100.0 + GRACE_SECONDS) == AP_UP

    def test_no_ap_before_grace(self):
        state = PolicyState()
        decide(_snap(), state, 100.0)
        assert decide(_snap(), state, 100.0 + GRACE_SECONDS - 1) is None

    def test_reconnect_within_grace_cancels_fallback(self):
        state = PolicyState()
        decide(_snap(), state, 100.0)
        decide(_snap(wifi_client_active=True), state, 110.0)
        # Disconnect again much later: the grace clock must restart.
        assert decide(_snap(), state, 500.0) is None
        assert state.disconnected_since == 500.0


@pytest.mark.unit
class TestIdleApClientRetry:
    def _aged_state(self, now):
        """State as it looks after the AP has been up for a while."""
        return PolicyState(last_client_retry=now - CLIENT_RETRY_SECONDS)

    def test_idle_ap_retries_client(self):
        now = 1000.0
        snap = _snap(ap_active=True, ap_stations=0)
        assert decide(snap, self._aged_state(now), now) == AP_DOWN

    def test_occupied_ap_never_dropped(self):
        now = 1000.0
        snap = _snap(ap_active=True, ap_stations=2)
        assert decide(snap, self._aged_state(now), now) is None

    def test_no_retry_before_interval(self):
        now = 1000.0
        state = PolicyState(last_client_retry=now - CLIENT_RETRY_SECONDS + 5)
        assert decide(_snap(ap_active=True), state, now) is None

    def test_first_observation_arms_but_does_not_retry(self):
        # An externally-activated AP (e.g. at boot) must not be dropped on
        # the daemon's first look; the retry clock starts then.
        state = PolicyState()
        assert decide(_snap(ap_active=True), state, 1000.0) is None
        assert state.last_client_retry == 1000.0

    def test_retry_then_fallback_restores_ap(self):
        # Full cycle: idle AP dropped for a retry, no client appears,
        # grace expires, AP comes back.
        now = 1000.0
        state = self._aged_state(now)
        assert decide(_snap(ap_active=True, ap_stations=0), state, now) == AP_DOWN
        assert decide(_snap(), state, now + GRACE_SECONDS) == AP_UP

    def test_retry_then_client_joins(self):
        now = 1000.0
        state = self._aged_state(now)
        assert decide(_snap(ap_active=True, ap_stations=0), state, now) == AP_DOWN
        assert decide(_snap(wifi_client_active=True), state, now + 10) is None
        assert state.disconnected_since is None
