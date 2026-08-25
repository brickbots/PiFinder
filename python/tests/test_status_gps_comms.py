"""
Unit tests for the STATUS screen's GPS comms row: how a published GPS event
becomes the row's value, and a width guard proving every event name we can
emit still fits its column on every panel.

The row is the whole user-facing point of the comms plumbing -- see
docs/ax/gps/CONTEXT.md and docs/adr/0032.
"""

import time

import pytest
from PIL import Image, ImageDraw

# Installs the _() gettext builtin the UI modules rely on; must precede ui imports.
import PiFinder.i18n  # noqa: F401

from PiFinder.displays import get_display
from PiFinder.gps_ubx_parser import CHECKSUM_MARKER, MARKER_PREFIX, NAVMessageId
from PiFinder.ui.status import UIStatus, _format_comms_age, _format_gps_comms
from PiFinder.ui.ui_utils import SpaceCalculatorFixed

pytestmark = pytest.mark.unit


# Every event name that can reach the row. The NAV names are derived from the
# parser's own table so a newly registered message class is width-checked
# automatically rather than quietly overflowing.
UBX_MESSAGE_NAMES = [f"NAV-{msg.name}" for msg in NAVMessageId]
GPSD_MESSAGE_NAMES = ["TPV", "SKY"]
MARKER_NAMES = [CHECKSUM_MARKER, f"{MARKER_PREFIX}FFFF"]
FAKE_MESSAGE_NAMES = ["FAKE"]
ALL_EVENT_NAMES = (
    UBX_MESSAGE_NAMES + GPSD_MESSAGE_NAMES + MARKER_NAMES + FAKE_MESSAGE_NAMES
)


def make_status(display_hardware):
    """A minimal UIStatus carrying only what _render_row touches, backed by a
    real headless display so the fonts and column width are the real ones."""
    display = get_display(display_hardware)
    s = UIStatus.__new__(UIStatus)
    s.display_class = display
    s.colors = display.colors
    s.fonts = display.fonts
    s.draw = ImageDraw.Draw(Image.new("RGBA", display.resolution), mode="RGBA")
    s.spacecalc = SpaceCalculatorFixed(display.fonts.base.line_length)
    s.value_scrollers = {}
    return s


# --- The value ---------------------------------------------------------------


def test_nothing_ever_received_reads_as_empty():
    # Distinct from a frozen name with a climbing age, which means the link
    # died rather than never having spoken.
    assert _format_gps_comms(None) == "--"


def test_nav_prefix_is_stripped():
    # NAV-TIMEGPS (11) would not fit the value column; TIMEGPS (7) does.
    assert _format_gps_comms(("NAV-TIMEGPS", time.monotonic())).startswith("TIMEGPS ")


def test_marker_name_is_shown_verbatim():
    assert _format_gps_comms((CHECKSUM_MARKER, time.monotonic())).startswith("?CKSUM ")


def test_gpsd_class_is_shown_verbatim():
    assert _format_gps_comms(("SKY", time.monotonic())).startswith("SKY ")


def test_age_is_measured_against_the_monotonic_clock():
    """The stamp is monotonic, so the age must be too -- the GPS is what sets
    the wall clock, and a wall-clock age inverts the instant a fix lands."""
    value = _format_gps_comms(("NAV-SOL", time.monotonic() - 12.0))

    assert value.startswith("SOL 12.")


# --- Age bucketing -----------------------------------------------------------


@pytest.mark.parametrize(
    "age, expected",
    [
        (0.0, "0.0s"),
        (0.44, "0.4s"),
        (47.23, "47.2s"),
        (99.9, "99.9s"),
        (99.99, "2m"),  # rounds out of the seconds bucket rather than to 100.0s
        (120.0, "2m"),
        (5999.0, "100m"),
        (6000.0, "2h"),
        (99999.0, "28h"),
    ],
)
def test_age_buckets(age, expected):
    assert _format_comms_age(age) == expected


def test_age_never_goes_negative():
    # Monotonic clocks are per-host, so a stamp fractionally ahead of ours is
    # not worth rendering as "-0.0s".
    assert _format_comms_age(-0.3) == "0.0s"


@pytest.mark.parametrize("age", [0.0, 47.2, 99.9, 5999.0, 999999.0])
def test_age_stays_within_five_characters(age):
    assert len(_format_comms_age(age)) <= 5


# --- Width -------------------------------------------------------------------


@pytest.mark.parametrize("display_hardware", ["headless", "headless_176"])
@pytest.mark.parametrize("name", ALL_EVENT_NAMES)
def test_every_event_name_fits_its_column(display_hardware, name):
    """Width regression guard: the row must render statically, never falling
    back to the horizontal scroller, for any event we can publish."""
    status = make_status(display_hardware)
    # 999999s is the widest age bucket; pair it with the widest names.
    value = _format_gps_comms((name, time.monotonic() - 999999.0))

    line = status._render_row("GPS MSG", value)

    assert len(line) <= status.spacecalc.width
    assert "GPS MSG" not in status.value_scrollers  # fits without scrolling


@pytest.mark.parametrize("display_hardware", ["headless", "headless_176"])
def test_row_key_is_exactly_the_padded_key_width(display_hardware):
    # _render_row pads keys to 7; a longer key would eat into the value column
    # and silently push the widest names into the scroller.
    assert len("GPS MSG") == 7
    status = make_status(display_hardware)
    assert status._render_row("GPS MSG", "SOL 0.4s").startswith("GPS MSG")
