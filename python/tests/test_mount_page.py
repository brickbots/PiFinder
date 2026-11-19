"""The mount page of Object Details (ui/mount_page.py)."""

import time

import pytest
from PIL import Image, ImageDraw

from PiFinder.displays import get_display
from PiFinder.mountcontrol_interface import meet_text
from PiFinder.target_follow import MeetPoint
from PiFinder.types.mount import MountStatus
from PiFinder.ui.mount_page import (
    band_texts,
    PRESS_FLASH_S,
    MountPageState,
    _fit,
    _progress,
    MountSetup,
    _status_texts,
    draw_connect_page,
    draw_mount_page,
    is_connected,
    key_labels,
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


def test_band_texts_for_each_connection_state():
    assert _status_texts(None, NOW)[:1] == ("NO STATUS",)
    unknown = MountStatus("MOUNT_UNKNOWN", "Not connected", None, 0.25, "SAL-33", NOW)
    phase, _d, detail, live, connected = _status_texts(unknown, NOW)
    assert (phase, detail, live, connected) == (
        "NOT CONNECTED",
        "Press 1 to connect",
        True,
        False,
    )
    failed = MountStatus(
        "MOUNT_UNKNOWN", "Not connected", None, 0.25, "SAL-33", NOW, "Mount not found"
    )
    assert _status_texts(failed, NOW)[2] == "Mount not found"
    connecting = MountStatus(
        "MOUNT_INIT_TELESCOPE", "Connecting", None, 0.25, "SAL-33", NOW
    )
    texts = _status_texts(connecting, NOW)
    assert (texts[0], texts[2], texts[4]) == ("CONNECTING", "SAL-33", False)
    assert _status_texts(_status(), NOW)[4] is True


def test_key_one_connects_without_a_mount():
    assert key_labels(True)[1][1] == "Init"
    assert key_labels(False)[1][1] == "Connect"


def test_key_numbers_show_after_opening():
    state = MountPageState()
    state.open(NOW)
    assert state.showing_numbers(NOW + 1.0)
    assert not state.showing_numbers(NOW + 2.5)


@pytest.mark.parametrize("display", ["headless", "headless_176", "headless_320"])
@pytest.mark.parametrize(
    "status",
    [
        None,
        MountStatus("MOUNT_UNKNOWN", "", None, 0.25, "SAL-33", NOW, "Mount not found"),
        MountStatus("MOUNT_INIT_TELESCOPE", "", None, 0.25, "SAL-33", NOW),
    ],
)
def test_connect_page_draws_inside_the_screen(display, status):
    d = get_display(display)
    image = Image.new("RGB", (d.resX, d.resY))
    setup = MountSetup("LX200 OnStep", "wifi", "", 9600, "192.168.0.1:9999")
    draw_connect_page(
        ImageDraw.Draw(image),
        d,
        d.fonts,
        d.colors,
        status,
        setup,
        MountPageState(),
        NOW,
    )
    assert image.crop((0, d.resY - 3, d.resX, d.resY)).getbbox() is not None


def test_is_connected():
    assert not is_connected(None, NOW)
    assert not is_connected(MountStatus("MOUNT_UNKNOWN", "", None, 0.25, "x", NOW), NOW)
    assert not is_connected(
        MountStatus("MOUNT_INIT_TELESCOPE", "", None, 0.25, "x", NOW), NOW
    )
    assert is_connected(_status(), NOW)
    assert not is_connected(_status(), NOW + 60)


def test_link_text():
    assert MountSetup("x", "usb", "/dev/ttyACM0", 9600, "").link_text() == (
        "USB ttyACM0 9600"
    )
    assert MountSetup("x", "wifi", "", 9600, "10.42.0.23:9998").link_text() == (
        "WiFi 10.42.0.23:9998"
    )
    assert MountSetup("x", "wifi", "", 9600, "").link_text() == "WiFi driver default"


FOLLOW = "MOUNT_TARGET_FOLLOW"
# The band texts of each follow stage, with the distance to the target.
FOLLOW_BANDS = [
    ("slewing", FOLLOW, "Follow slew", 24.6),
    ("slewing far", FOLLOW, "Follow slew", 124.6),
    ("meet wait", FOLLOW, meet_text(453.2, MeetPoint(0.0, 20.0, 225.0)), 0.001),
    ("meet wait far", FOLLOW, meet_text(453.2, MeetPoint(0.0, 20.0, 225.0)), 124.6),
    ("wait", FOLLOW, "Follow in 12s -0.4s", 0.001),
    ("following", FOLLOW, "Following", 0.001),
    ("correction", FOLLOW, "Follow -0.4s", 0.001),
    ("large correction", FOLLOW, "Follow +12.3s", 3.4),
    ("pass", FOLLOW, "Follow pass", 0.001),
    ("pass correction", FOLLOW, "Follow pass -0.4s", 0.001),
    ("pass end", "MOUNT_TRACKING", "Tracking", 0.001),
]


@pytest.mark.parametrize("display", ["headless", "headless_176", "headless_320"])
@pytest.mark.parametrize(
    "phase,text,distance",
    [b[1:] for b in FOLLOW_BANDS],
    ids=[b[0] for b in FOLLOW_BANDS],
)
def test_follow_band_shows_the_whole_status(display, phase, text, distance):
    d = get_display(display)
    image = Image.new("RGB", (d.resX, d.resY))
    draw = ImageDraw.Draw(image)
    status = _status(phase, text, distance)
    band, shown_distance, rest, detail, _live, _connected = band_texts(
        draw, d.fonts, d.resX, status, NOW
    )
    line = rest + detail
    # No ellipsis, and each word of the status is on the band or the line
    # under it, in the same order.
    assert "…" not in band + line
    assert f"{band} {line}".upper().split()[: len(text.split())] == (
        text.upper().split()
    )
    assert shown_distance
    assert line.endswith("step 15.0'")
    # Each line fits the screen width.
    room = d.resX - draw.textlength(shown_distance, font=d.fonts.bold.font) - 2
    assert draw.textlength(band, font=d.fonts.bold.font) <= room
    assert draw.textlength(line, font=d.fonts.small.font) <= d.resX
    draw_mount_page(draw, d, d.fonts, d.colors, status, MountPageState(), NOW)


@pytest.mark.parametrize(
    "text,band,rest",
    [
        ("Meet 7:34 20°SW", "MEET 7:34", "20°SW"),
        ("Follow in 12s -0.4s", "FOLLOW IN 12S", "-0.4s"),
        ("Follow pass -0.4s", "FOLLOW PASS", "-0.4s"),
        ("Follow -0.4s", "FOLLOW -0.4S", ""),
    ],
)
def test_small_screen_puts_the_rest_under_the_band(text, band, rest):
    d = get_display("headless")
    draw = ImageDraw.Draw(Image.new("RGB", (d.resX, d.resY)))
    status = _status(FOLLOW, text, 0.001)
    texts = band_texts(draw, d.fonts, d.resX, status, NOW)
    assert texts[:4] == (band, "<1'", rest, ("  " if rest else "") + "step 15.0'")
