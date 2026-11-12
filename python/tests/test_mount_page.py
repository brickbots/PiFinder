"""The mount page of Object Details (ui/mount_page.py)."""

import time

import pytest
from PIL import Image, ImageDraw

from PiFinder.displays import get_display
from PiFinder.types.mount import MountStatus
from PiFinder.ui.mount_page import (
    PRESS_FLASH_S,
    MountPageState,
    _fit,
    _progress,
    draw_mount_page,
)

pytestmark = pytest.mark.unit

NOW = 1000.0


def _status(phase="MOUNT_TRACKING", text="Tracking", distance=None):
    return MountStatus(phase, text, distance, 0.25, "SAL-33", NOW)


@pytest.mark.parametrize("display", ["headless", "headless_176", "headless_320"])
@pytest.mark.parametrize(
    "status",
    [
        None,
        _status(),
        _status("MOUNT_TARGET_ACQUISITION_MOVE", "Slewing", 24.6),
        _status("MOUNT_TARGET_ACQUISITION_REFINE", "Refining 2/3", 1.76),
        _status("MOUNT_DRIFT_COMPENSATION", "On target", 0.001),
    ],
)
def test_page_draws_inside_the_screen(display, status):
    d = get_display(display)
    image = Image.new("RGB", (d.resX, d.resY))
    state = MountPageState()
    state.press(5, NOW)
    draw_mount_page(ImageDraw.Draw(image), d, d.fonts, d.colors, status, state, NOW)
    # Something is drawn below the title bar, and the bottom row (STOP) too.
    assert image.crop((0, d.titlebar_height, d.resX, d.resY)).getbbox() is not None
    assert image.crop((0, d.resY - 3, d.resX, d.resY)).getbbox() is not None


def test_key_flash():
    state = MountPageState()
    state.press(8, NOW)
    assert state.flashing(8, NOW + 0.1)
    assert not state.flashing(2, NOW + 0.1)
    assert not state.flashing(8, NOW + PRESS_FLASH_S + 0.01)


def test_progress_of_a_slew():
    state = MountPageState()
    assert _progress(state, _status()) is None
    moving = "MOUNT_TARGET_ACQUISITION_MOVE"
    assert _progress(state, _status(moving, "Slewing", 40.0)) == pytest.approx(0.0)
    state.last_phase = moving
    assert _progress(state, _status(moving, "Slewing", 10.0)) == pytest.approx(0.75)
    # The distance can grow at the start of a slew (a flip): it is the new
    # start distance.
    assert _progress(state, _status(moving, "Slewing", 50.0)) == pytest.approx(0.0)
    # A new slew starts the bar again.
    state.last_phase = "MOUNT_TRACKING"
    assert _progress(state, _status(moving, "Slewing", 5.0)) == pytest.approx(0.0)


def test_fit_cuts_long_text():
    font = get_display("headless").fonts.bold
    assert _fit("ON TARGET", font, 200) == "ON TARGET"
    cut = _fit("REFINING 2/3 WITH A LONG TAIL", font, 60)
    assert cut.endswith("…") and len(cut) * font.width <= 60 + font.width


def test_status_is_live_only_when_fresh(monkeypatch):
    d = get_display("headless")
    old = MountStatus("MOUNT_TRACKING", "Tracking", None, 0.25, "x", time.time() - 60)
    image = Image.new("RGB", (d.resX, d.resY))
    draw_mount_page(ImageDraw.Draw(image), d, d.fonts, d.colors, old, MountPageState())
    fresh = Image.new("RGB", (d.resX, d.resY))
    draw_mount_page(
        ImageDraw.Draw(fresh),
        d,
        d.fonts,
        d.colors,
        MountStatus("MOUNT_TRACKING", "Tracking", None, 0.25, "x", time.time()),
        MountPageState(),
    )
    # The stale page is dimmer: its brightest status pixel is lower.
    band = (0, d.titlebar_height, d.resX, d.titlebar_height + 16)
    assert max(image.crop(band).getextrema()[0]) < max(fresh.crop(band).getextrema()[0])
