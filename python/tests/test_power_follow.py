"""A mount follow keeps the PiFinder awake.

A key press that wakes the PiFinder does nothing else. During the wait at
the meet point of a satellite follow, a sleep would lose the "I see it"
press. The follow status of the mount process holds the PiFinder awake;
after the follow the sleep timeout counts again.
"""

from unittest.mock import Mock

import pytest

from PiFinder import main
from PiFinder.types.mount import MountStatus, keeps_awake

pytestmark = pytest.mark.unit

SLEEP_TIMEOUT_S = 30


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def status(phase: str, updated: float) -> MountStatus:
    return MountStatus(phase, "Meet in 2:30", 1.0, 0.5, "", updated)


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(main.time, "time", clock)
    monkeypatch.setattr(main, "set_brightness", Mock())
    return clock


def make_power_manager() -> main.PowerManager:
    cfg = Mock()
    cfg.get_option.side_effect = {
        "sleep_timeout": "30s",
        "screen_off_timeout": "Off",
        "display_brightness": 100,
    }.get
    return main.PowerManager(cfg, Mock(), Mock())


def menu(keep_awake: bool = False) -> Mock:
    return Mock(keep_awake=Mock(return_value=keep_awake))


def snapshot(mount_status) -> Mock:
    return Mock(mount_status=Mock(return_value=mount_status))


def run(power, clock, seconds: float, phase: str) -> None:
    """Advance the clock in steps of one second; the mount process writes a
    new status each step."""
    for _step in range(int(seconds)):
        clock.now += 1.0
        frame = snapshot(status(phase, clock.now))
        power.update(keep_awake=main.must_stay_awake(menu(), frame))


def test_no_sleep_during_a_follow_and_sleep_again_after_it(clock):
    power = make_power_manager()
    # The meet wait and the follow: much longer than the sleep timeout.
    run(power, clock, 5 * SLEEP_TIMEOUT_S, "MOUNT_TARGET_FOLLOW")
    assert power.power_state == 1
    # After the follow the mount tracks. The timeout counts from the end.
    run(power, clock, SLEEP_TIMEOUT_S - 1, "MOUNT_TRACKING")
    assert power.power_state == 1
    run(power, clock, 2, "MOUNT_TRACKING")
    assert power.power_state == 0


def test_the_first_arrow_after_a_long_meet_wait_is_not_a_wake_press(clock):
    power = make_power_manager()
    run(power, clock, 4 * SLEEP_TIMEOUT_S, "MOUNT_TARGET_FOLLOW")
    # The main loop drops a key press only when register_activity wakes.
    assert power.register_activity() is False


def test_a_follow_that_starts_during_a_sleep_wakes_the_pifinder(clock):
    power = make_power_manager()
    run(power, clock, SLEEP_TIMEOUT_S + 2, "MOUNT_TRACKING")
    assert power.power_state == 0
    run(power, clock, 1, "MOUNT_TARGET_FOLLOW")
    assert power.power_state == 1


def test_a_stale_or_missing_status_does_not_keep_the_pifinder_awake():
    assert keeps_awake(status("MOUNT_TARGET_FOLLOW", 100.0), now=101.0)
    assert not keeps_awake(status("MOUNT_TARGET_FOLLOW", 100.0), now=200.0)
    assert not keeps_awake(status("MOUNT_TRACKING", 100.0), now=101.0)
    assert not keeps_awake(None)
    assert main.must_stay_awake(menu(keep_awake=True), snapshot(None))
    assert not main.must_stay_awake(menu(), snapshot(None))
