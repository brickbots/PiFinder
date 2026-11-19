"""
Unit tests for the UI's reduced shared-state traffic: frames go to shared
state only when they change, and the title bar's rotating SQM/constellation
text reads the frame's state snapshot.
"""

from types import SimpleNamespace

import pytest
from PIL import Image

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401

from PiFinder.state_snapshot import StateSnapshot
from PiFinder.ui.base import RotatingInfoDisplay, UIModule

pytestmark = pytest.mark.unit


class CountingState:
    def __init__(self):
        self.screens = []

    def set_screen(self, image):
        self.screens.append(image)


@pytest.fixture(autouse=True)
def fresh_frame_cache(monkeypatch):
    monkeypatch.setattr(UIModule, "_published_frame", None)


def test_publish_screen_skips_an_unchanged_frame():
    state = CountingState()
    frame = Image.new("RGB", (8, 8))
    UIModule.publish_screen(state, frame)
    UIModule.publish_screen(state, frame.copy())
    assert len(state.screens) == 1

    changed = frame.copy()
    changed.putpixel((0, 0), (255, 0, 0))
    UIModule.publish_screen(state, changed)
    assert len(state.screens) == 2


def test_publish_screen_resends_a_frame_after_a_different_one():
    # A popup sent between two equal frames must not hide the second one.
    state = CountingState()
    frame = Image.new("RGB", (8, 8))
    popup = Image.new("RGB", (8, 8), (255, 0, 0))
    for image in (frame, popup, frame):
        UIModule.publish_screen(state, image)
    assert len(state.screens) == 3


def test_rotating_info_reads_the_frame_snapshot():
    snapshot = StateSnapshot(
        {
            "sqm": SimpleNamespace(value=19.5, last_update=1.0),
            "solution": SimpleNamespace(constellation="Cyg"),
        }
    )
    display = RotatingInfoDisplay()
    current, previous, _ = display.update(snapshot)
    assert {current, previous} == {"19.5", "Cyg"}
