"""
Unit tests for the STATUS screen's per-row rendering (UIStatus._render_row):
values that fit render statically, values that overflow their column scroll,
and a row flips correctly between the two as its value changes (e.g. the IP
address or SSID changing at runtime), dropping the scroller again when a value
shrinks back to fitting.
"""

import pytest
from PIL import Image, ImageDraw

# Installs the _() gettext builtin the UI modules rely on; must precede ui imports.
import PiFinder.i18n  # noqa: F401

from PiFinder.displays import get_display
from PiFinder.ui.status import UIStatus
from PiFinder.ui.ui_utils import SpaceCalculatorFixed

pytestmark = pytest.mark.unit


@pytest.fixture
def status():
    """A minimal UIStatus carrying only the attributes _render_row /
    _scrolled_value touch, backed by a real headless display (real fonts /
    colors), constructed without the heavy UIModule.__init__."""
    display = get_display("headless")
    s = UIStatus.__new__(UIStatus)
    s.display_class = display
    s.colors = display.colors
    s.fonts = display.fonts
    s.draw = ImageDraw.Draw(Image.new("RGBA", display.resolution), mode="RGBA")
    s.spacecalc = SpaceCalculatorFixed(display.fonts.base.line_length)
    s.value_scrollers = {}
    return s


def _field(status, key="IP"):
    # _render_row left-pads the key to 7 chars, so the value column is width - 7.
    return status.spacecalc.width - len(f"{key:<7}")


def test_short_value_renders_static_without_scroller(status):
    field = _field(status)
    short = "x" * (field - 1)
    line = status._render_row("IP", short)
    assert "IP" not in status.value_scrollers  # no scroller for a fitting value
    assert short in line  # full value stays visible


def test_long_value_creates_scroller(status):
    field = _field(status)
    long = "1" * (field + 5)
    status._render_row("IP", long)
    assert "IP" in status.value_scrollers
    assert status.value_scrollers["IP"].text == long


def test_static_to_scroller_transition(status):
    field = _field(status)
    status._render_row("IP", "x" * (field - 1))  # fits -> static
    assert "IP" not in status.value_scrollers
    status._render_row("IP", "9" * (field + 5))  # now overflows -> scroller appears
    assert "IP" in status.value_scrollers


def test_scroller_to_static_transition_drops_scroller(status):
    field = _field(status)
    status._render_row("IP", "9" * (field + 5))  # overflows -> scroller
    assert "IP" in status.value_scrollers
    status._render_row("IP", "x" * (field - 1))  # fits again -> scroller dropped
    assert "IP" not in status.value_scrollers


def test_value_change_while_overflowing_recreates_scroller(status):
    field = _field(status)
    long_a = "a" * (field + 5)
    long_b = "b" * (field + 8)
    status._render_row("IP", long_a)
    scroller_a = status.value_scrollers["IP"]
    assert scroller_a.text == long_a
    status._render_row("IP", long_b)
    scroller_b = status.value_scrollers["IP"]
    assert scroller_b.text == long_b
    assert scroller_b is not scroller_a  # recreated for the new value


def test_rows_scroll_independently(status):
    field_ip = status.spacecalc.width - len(f"{'IP':<7}")
    field_ssid = status.spacecalc.width - len(f"{'SSID':<7}")
    status._render_row("IP", "1" * (field_ip + 5))
    status._render_row("SSID", "N" * (field_ssid + 5))
    assert "IP" in status.value_scrollers
    assert "SSID" in status.value_scrollers
    assert status.value_scrollers["IP"] is not status.value_scrollers["SSID"]


def test_dynamic_label_row_unpacks_label_and_value(status):
    # The GPS row supplies a runtime-computed label (live sat count) as
    # [label, value], so _render_row uses that label rather than the dict key.
    line = status._render_row("GPS", ["GPS 7/12", "1.0/2.0"])
    assert line.startswith("GPS 7/12")  # list label used as the row label
    assert "1.0/2.0" in line  # short value rendered statically
