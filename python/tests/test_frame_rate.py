"""Unit tests for the shared UI frame counter (PiFinder.ui.base.FrameRate)."""

import pytest

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401

from PiFinder.ui import base
from PiFinder.ui.base import FrameRate, UIModule

pytestmark = pytest.mark.unit


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(base.time, "monotonic", fake)
    return fake


# Frame periods are powers of two, so the clock sums are exact.
def run_frames(frame_rate, clock, count, period):
    for _ in range(count):
        clock.now += period
        frame_rate.tick()


def test_rate_over_one_second_window(clock):
    frame_rate = FrameRate()
    assert frame_rate.fps == 0
    run_frames(frame_rate, clock, 31, 1 / 32)
    assert frame_rate.fps == 0
    run_frames(frame_rate, clock, 1, 1 / 32)
    assert frame_rate.fps == 32


def test_rate_divides_by_the_real_window_length(clock):
    # 5 frames that take 1.25 s in total are 4 frames per second.
    frame_rate = FrameRate()
    run_frames(frame_rate, clock, 5, 0.25)
    assert frame_rate.fps == 4


def test_slow_frame_lowers_the_next_value(clock):
    frame_rate = FrameRate()
    run_frames(frame_rate, clock, 32, 1 / 32)
    # One frame that takes 0.5 s, then fast frames to the end of the window.
    run_frames(frame_rate, clock, 1, 0.5)
    run_frames(frame_rate, clock, 16, 1 / 32)
    assert frame_rate.fps == 17


def test_all_screens_share_one_counter():
    assert isinstance(UIModule.frame_rate, FrameRate)
    assert UIModule.__dict__["frame_rate"] is UIModule.frame_rate
