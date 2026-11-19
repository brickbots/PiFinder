"""Tests for shared-state dead-manager detection and graceful shutdown.

When the multiprocessing Manager that owns SharedStateObj dies, worker
proxy calls raise BrokenPipeError / ConnectionResetError / EOFError. Workers
must treat this as terminal (log once, stop) instead of retrying forever.
"""

import pytest

from PiFinder import state_utils


@pytest.mark.unit
@pytest.mark.parametrize(
    "exc",
    [
        BrokenPipeError(32, "Broken pipe"),
        ConnectionResetError(104, "Connection reset by peer"),
        EOFError(),
        state_utils.SharedStateLost("manager gone"),
    ],
)
def test_dead_manager_errors_detected(exc):
    assert state_utils.is_dead_manager_error(exc) is True


@pytest.mark.unit
@pytest.mark.parametrize("exc", [ValueError(), RuntimeError(), KeyError(), OSError()])
def test_live_manager_errors_not_flagged(exc):
    assert state_utils.is_dead_manager_error(exc) is False


class _Healthy:
    def power_state(self):
        return 1


class _PoweredOff:
    def power_state(self):
        return 0


class _DeadManager:
    def __init__(self, exc):
        self._exc = exc

    def power_state(self):
        raise self._exc


@pytest.mark.unit
def test_sleep_for_framerate_awake_when_powered():
    state_utils._last_wake = None
    assert state_utils.sleep_for_framerate(_Healthy(), limit_framerate=False) is False


@pytest.mark.unit
def test_sleep_for_framerate_sleeps_when_powered_off():
    assert state_utils.sleep_for_framerate(_PoweredOff()) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "exc",
    [
        BrokenPipeError(32, "Broken pipe"),
        ConnectionResetError(104, "reset"),
        EOFError(),
    ],
)
def test_sleep_for_framerate_translates_dead_manager(exc):
    with pytest.raises(state_utils.SharedStateLost) as info:
        state_utils.sleep_for_framerate(_DeadManager(exc))
    # The original connection error is preserved as the cause and is still
    # recognised by the shared detector.
    assert info.value.__cause__ is exc
    assert state_utils.is_dead_manager_error(info.value) is True
