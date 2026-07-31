"""
Unit tests for ``PiFinder.bringup`` — the bench validation tool
(``docs/ax/bringup/CONTEXT.md``).

Everything here runs off-Pi. That is not a limitation being worked around, it
is the design: ``bringup`` keeps its pure logic away from its hardware seams
and imports every hardware module lazily, so the parts worth testing —
verdict arithmetic, the config.txt parse, switch bookkeeping, layout — are
testable on a dev machine with no board attached.

The last test is the load-bearing one: it re-imports the module in a
subprocess with ``RPi.GPIO``, ``board``, ``rpi_hardware_pwm`` and
``adafruit_bno055`` forcibly unimportable, which is what keeps those imports
lazy as the module grows.
"""

import inspect
import re
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from PiFinder import bringup, displays, keypad
from PiFinder.bringup import (
    CheckResult,
    GridState,
    Kind,
    PowerHold,
    Status,
    backlight_duty,
    compute_verdict,
    describe_positions,
    format_summary,
    grid_layout,
    parse_pwm_overlay,
    power_cell_label,
    request_shutdown,
)

PYTHON_DIR = Path(__file__).resolve().parents[1]


# --- Pre-flight: PWM overlay parsing ---------------------------------------


@pytest.mark.unit
def test_parse_pwm_overlay_single_channel_is_what_the_repo_provisions():
    """``pifinder_setup.sh`` writes exactly this line: ch1 -> gpio13 for the
    keypad backlight, and nothing at all for the buzzer's ch0."""
    routing = parse_pwm_overlay("dtoverlay=pwm,pin=13,func=4\n")
    assert routing == {1: 13}
    assert 0 not in routing


@pytest.mark.unit
def test_parse_pwm_overlay_two_channel():
    routing = parse_pwm_overlay("dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4\n")
    assert routing == {0: 12, 1: 13}


@pytest.mark.unit
def test_parse_pwm_overlay_uses_the_overlay_defaults():
    """A bare ``pwm`` defaults to pin 12 (ch0); a bare ``pwm-2chan`` to 12/13."""
    assert parse_pwm_overlay("dtoverlay=pwm\n") == {0: 12}
    assert parse_pwm_overlay("dtoverlay=pwm-2chan\n") == {0: 12, 1: 13}


@pytest.mark.unit
def test_parse_pwm_overlay_absent():
    config = "dtparam=spi=on\ndtoverlay=uart3\ndtoverlay=gpio-poweroff,gpiopin=14\n"
    assert parse_pwm_overlay(config) == {}
    assert parse_pwm_overlay("") == {}


@pytest.mark.unit
def test_parse_pwm_overlay_ignores_commented_out_lines():
    """Both a fully commented line and a trailing comment."""
    assert parse_pwm_overlay("#dtoverlay=pwm-2chan,pin=12,pin2=13\n") == {}
    assert parse_pwm_overlay("  # dtoverlay=pwm,pin=13,func=4\n") == {}
    assert parse_pwm_overlay("dtoverlay=pwm,pin=13,func=4  # backlight\n") == {1: 13}


@pytest.mark.unit
def test_parse_pwm_overlay_later_line_wins():
    config = "dtoverlay=pwm,pin=13,func=4\ndtoverlay=pwm,pin=19,func=2\n"
    assert parse_pwm_overlay(config) == {1: 19}


@pytest.mark.unit
def test_preflight_routing_properties():
    routed = bringup.Preflight(
        i2c_bus_present=True, config_path="/boot/config.txt", pwm_routing={0: 12, 1: 13}
    )
    assert routed.buzzer_routed is True
    assert routed.backlight_routed is True

    # What this repo provisions today: the backlight is routed, the buzzer is
    # exported to no pin at all.
    partial = bringup.Preflight(
        i2c_bus_present=True, config_path="/boot/config.txt", pwm_routing={1: 13}
    )
    assert partial.backlight_routed is True
    assert partial.buzzer_routed is False
    assert "NOT ROUTED" in bringup.format_preflight(partial)

    # No config.txt to read (a dev box): unknown, not "not routed".
    unknown = bringup.Preflight(i2c_bus_present=False, config_path=None)
    assert unknown.buzzer_routed is None
    assert unknown.backlight_routed is None
    summary = bringup.format_preflight(unknown)
    assert "UNKNOWN" in summary and "MISSING" in summary


# --- The verdict -----------------------------------------------------------


def _probed(name, status):
    return CheckResult(name, Kind.PROBED, status, "detail")


def _exercised(name, status):
    return CheckResult(name, Kind.EXERCISED, status, "detail")


def _witnessed(name, status=Status.EMITTED):
    return CheckResult(name, Kind.WITNESSED, status, "detail")


def _all_passing():
    return [
        _probed("IMU", Status.PASS),
        _probed("CHARGER", Status.PASS),
        _exercised("SWITCHES", Status.PASS),
    ]


@pytest.mark.unit
def test_verdict_passes_only_when_every_gating_check_passes():
    assert compute_verdict(_all_passing()) is True


@pytest.mark.unit
def test_verdict_ignores_witnessed_results_entirely():
    """Witnessed checks never move the verdict, whatever they report."""
    gating = _all_passing()
    for status in (Status.EMITTED, Status.SKIPPED):
        assert compute_verdict(gating + [_witnessed("BUZZER", status)]) is True

    failing = gating[:-1] + [_exercised("SWITCHES", Status.FAIL)]
    for status in (Status.EMITTED, Status.SKIPPED):
        assert compute_verdict(failing + [_witnessed("SCREEN", status)]) is False


@pytest.mark.unit
def test_verdict_fails_on_a_missing_switch():
    results = _all_passing()[:-1] + [_exercised("SWITCHES", Status.FAIL)]
    assert compute_verdict(results) is False


@pytest.mark.unit
def test_verdict_fails_on_a_probe_failure():
    results = [_probed("IMU", Status.FAIL)] + _all_passing()[1:]
    assert compute_verdict(results) is False


@pytest.mark.unit
def test_verdict_fails_when_a_gating_check_was_skipped():
    """A pre-flight failure invalidates the check rather than blaming the
    board -- but the run did not verify that part, so it cannot pass."""
    results = [_probed("IMU", Status.SKIPPED)] + _all_passing()[1:]
    assert compute_verdict(results) is False


@pytest.mark.unit
def test_verdict_of_nothing_is_not_a_pass():
    assert compute_verdict([]) is False
    assert compute_verdict([_witnessed("SCREEN")]) is False


@pytest.mark.unit
def test_a_witnessed_check_cannot_carry_pass_or_fail():
    """The invariant the verdict rests on, enforced at construction."""
    for status in (Status.PASS, Status.FAIL):
        with pytest.raises(ValueError):
            CheckResult("BUZZER", Kind.WITNESSED, status)
    with pytest.raises(ValueError):
        CheckResult("IMU", Kind.PROBED, Status.EMITTED)


@pytest.mark.unit
def test_only_probed_and_exercised_kinds_gate():
    assert Kind.PROBED.gates and Kind.EXERCISED.gates
    assert not Kind.WITNESSED.gates


# --- The switch grid -------------------------------------------------------


@pytest.fixture
def grid():
    return GridState(keypad.REV4_POPULATED)


@pytest.mark.unit
def test_grid_starts_empty(grid):
    assert grid.seen_count == 0
    assert grid.expected_count == 18
    assert grid.missing == keypad.REV4_POPULATED
    assert not grid.complete


@pytest.mark.unit
def test_grid_press_and_release_edges(grid):
    edges = grid.update({(0, 0)})
    assert edges.pressed == frozenset({(0, 0)})
    assert edges.released == frozenset()
    assert edges.any_pressed

    # Still held on the next scan: not a new press.
    edges = grid.update({(0, 0)})
    assert edges.pressed == frozenset()
    assert not edges.any_pressed

    edges = grid.update(set())
    assert edges.released == frozenset({(0, 0)})
    assert not edges.any_pressed


@pytest.mark.unit
def test_grid_repeat_presses_do_not_double_count(grid):
    for _ in range(5):
        grid.update({(0, 0)})
        grid.update(set())
    assert grid.seen_count == 1


@pytest.mark.unit
def test_grid_held_is_not_seen(grid):
    """``seen`` is history, ``held`` is now -- a released switch stays seen."""
    grid.update({(1, 1)})
    assert (1, 1) in grid.held and (1, 1) in grid.seen
    grid.update(set())
    assert (1, 1) not in grid.held
    assert (1, 1) in grid.seen


@pytest.mark.unit
def test_a_stuck_position_stays_held(grid):
    """A solder bridge reads closed forever; the grid keeps showing it filled
    even though it has long since counted as seen."""
    for _ in range(10):
        grid.update({(2, 2)})
    assert grid.held == {(2, 2)}
    assert (2, 2) in grid.seen


@pytest.mark.unit
def test_grid_power_switch_is_tracked_separately(grid):
    """The power switch has no matrix position, and PASS needs it too."""
    for position in keypad.REV4_POPULATED:
        grid.update({position})
    grid.update(set())
    assert not grid.missing
    assert not grid.complete  # power never pressed

    edges = grid.update(set(), power_closed=True)
    assert edges.power_pressed
    assert grid.complete
    edges = grid.update(set(), power_closed=False)
    assert edges.power_released


@pytest.mark.unit
def test_grid_reports_closures_outside_the_population_map(grid):
    """A closure where the map says there is no switch is a miswire, a ghost,
    or a wrong map -- reported, never silently counted."""
    grid.update({(4, 0)})  # rev3's bottom row: unpopulated on rev4
    assert grid.unexpected == frozenset({(4, 0)})
    assert grid.seen_count == 0  # does not count toward the 18


@pytest.mark.unit
def test_describe_positions_names_the_key_each_switch_sends():
    assert describe_positions(frozenset({(1, 3)})) == "(1,3) PLUS"
    assert (
        describe_positions(frozenset({(3, 3), (4, 4)})) == "(3,3) SQUARE, (4,4) SQUARE"
    )
    assert describe_positions(frozenset({(0, 0)})) == "(0,0) 7"
    many = frozenset({(0, 0), (0, 1), (0, 2), (1, 0)})
    assert describe_positions(many).endswith("+1 more")


# --- The power hold --------------------------------------------------------


@pytest.mark.unit
def test_power_hold_arms_only_after_the_threshold():
    hold = PowerHold(threshold=1.0)

    assert not hold.update(True, 100.0)  # closes
    assert not hold.update(True, 100.5)  # halfway
    assert not hold.update(True, 100.99)
    assert hold.update(True, 101.0)  # threshold reached


@pytest.mark.unit
def test_power_hold_arms_exactly_once_while_held():
    """A power line that reads closed forever -- a stuck switch or a short --
    must not re-request a shutdown on every frame of the loop."""
    hold = PowerHold(threshold=1.0)
    hold.update(True, 0.0)
    assert hold.update(True, 1.0)
    for step in range(2, 20):
        assert not hold.update(True, float(step))


@pytest.mark.unit
def test_a_released_hold_rearms_and_does_not_fire():
    """Releasing before the threshold is how an accidental hold is aborted;
    the next press then starts a fresh second rather than resuming."""
    hold = PowerHold(threshold=1.0)
    hold.update(True, 0.0)
    hold.update(True, 0.9)
    assert not hold.update(False, 0.95)
    assert hold.progress == 0.0

    # A new press does not inherit the 0.9 s already served.
    assert not hold.update(True, 1.0)
    assert not hold.update(True, 1.5)
    assert hold.update(True, 2.0)


@pytest.mark.unit
def test_a_tap_never_arms_the_hold():
    """The SWITCHES check needs the power switch closed; a tap has to satisfy
    it without shutting the card down mid-run."""
    hold = PowerHold(threshold=1.0)
    for press in range(10):
        now = press * 0.5
        assert not hold.update(True, now)
        assert not hold.update(False, now + 0.05)


@pytest.mark.unit
def test_power_hold_progress_tracks_the_hold():
    hold = PowerHold(threshold=1.0)
    assert hold.progress == 0.0
    hold.update(True, 10.0)
    assert hold.progress == pytest.approx(0.0)
    hold.update(True, 10.25)
    assert hold.progress == pytest.approx(0.25)
    hold.update(True, 10.75)
    assert hold.progress == pytest.approx(0.75)
    # Never overshoots, even on a hold that outlives the threshold.
    hold.update(True, 20.0)
    assert hold.progress == 1.0


@pytest.mark.unit
def test_disabled_hold_never_arms_and_shows_no_bar():
    """``--no-power-shutdown``: the switch still reads closed for the SWITCHES
    check, but nothing arms and the cell must not draw a filling bar that
    promises a shutdown which will never come."""
    hold = PowerHold(threshold=1.0, enabled=False)
    for step in range(20):
        assert not hold.update(True, float(step))
        assert hold.progress == 0.0


@pytest.mark.unit
def test_the_hold_threshold_matches_the_running_application():
    """Bring-up and ``keyboard_pi`` answer the same gesture, so a builder
    learns "hold power" once. ``keyboard_pi`` spells its threshold inline."""
    source = (PYTHON_DIR / "PiFinder" / "keyboard_pi.py").read_text()
    assert (
        "time() - self.power_press_time > 1" in source
    ), "keyboard_pi's power threshold moved -- retune SHUTDOWN_HOLD_SECONDS"
    assert bringup.SHUTDOWN_HOLD_SECONDS == 1.0


@pytest.mark.unit
def test_power_cell_label_is_a_bar_only_while_held():
    assert power_cell_label(0.0) == "PWR"
    # One segment on the very first frame: the bar has to say "something is
    # happening" while there is still time to let go.
    assert power_cell_label(0.01) == "[#---]"
    assert power_cell_label(0.5) == "[##--]"
    assert power_cell_label(0.9) == "[###-]"
    # ...and full only at the threshold, never a moment before it.
    assert power_cell_label(0.99) != "[####]"
    assert power_cell_label(1.0) == "[####]"


@pytest.mark.unit
def test_power_cell_label_fits_the_cell_on_every_panel():
    """The label is drawn by the ordinary centred-cell path, so it has to fit
    the power cell at its narrowest -- the 128 px panel's 34 px cell."""
    labels = [power_cell_label(step / 20.0) for step in range(21)]
    # Every bar state is the same width, so the label never reflows mid-hold.
    assert {len(label) for label in labels if label != "PWR"} == {
        bringup.HOLD_BAR_SEGMENTS + 2
    }

    for display_cls in HEADLESS_DISPLAYS:
        display = display_cls()
        layout = grid_layout(display)
        for label in labels:
            assert label.isascii()  # the UI fonts carry no box-drawing glyphs
            width = display.fonts.small.width * len(label)
            assert width <= layout.power.widths[0], (
                f"{label!r} is {width}px in a {layout.power.widths[0]}px cell "
                f"on {display_cls.__name__}"
            )


@pytest.mark.unit
def test_shutdown_command_matches_sys_utils():
    """``bringup`` spells the shutdown command out instead of importing
    ``sys_utils`` (which needs ``pam`` / ``requests`` / ``sh`` and resolves
    ``wpa_cli`` at import time -- none guaranteed on a freshly imaged card).
    This is what keeps the two spellings in step.
    """
    source = (PYTHON_DIR / "PiFinder" / "sys_utils.py").read_text()
    assert (
        'sh.sudo("shutdown", "now")' in source
    ), "sys_utils.shutdown changed -- update SHUTDOWN_COMMAND"
    assert bringup.SHUTDOWN_COMMAND == ("sudo", "shutdown", "now")


@pytest.mark.unit
def test_request_shutdown_runs_the_command():
    calls = []

    def runner(command):
        calls.append(command)
        return 0

    assert request_shutdown(runner=runner) == 0
    assert calls == [["sudo", "shutdown", "now"]]


@pytest.mark.unit
def test_request_shutdown_reports_a_refusal():
    """A card without passwordless ``shutdown`` in sudoers leaves the builder
    reading SHUTTING DOWN on a board that is still up -- and reaching for the
    power, which is the one thing the gesture exists to prevent."""
    assert request_shutdown(runner=lambda command: 1) == 1


# --- The report ------------------------------------------------------------


@pytest.mark.unit
def test_format_summary_labels_every_kind():
    results = [
        _witnessed("SCREEN", Status.EMITTED),
        _witnessed("BUZZER", Status.SKIPPED),
        _probed("IMU", Status.PASS),
        _exercised("SWITCHES", Status.FAIL),
    ]
    lines = format_summary(results, verdict=False).splitlines()

    assert lines[0].startswith("SCREEN") and "emitted" in lines[0]
    assert "(witnessed)" in lines[0]
    assert lines[1].startswith("BUZZER") and "skipped" in lines[1]
    assert lines[2].startswith("IMU") and "PASS" in lines[2] and "(probed)" in lines[2]
    assert (
        lines[3].startswith("SWITCHES")
        and "FAIL" in lines[3]
        and "(exercised)" in lines[3]
    )
    assert lines[-1] == "VERDICT    FAIL"


@pytest.mark.unit
def test_format_summary_never_claims_a_witnessed_check_passed():
    """ "The buzzer passed" is not something the program can say."""
    results = [_witnessed("SCREEN"), _witnessed("BACKLIGHT"), _witnessed("BUZZER")]
    for line in format_summary(results, verdict=True).splitlines()[:-1]:
        assert "PASS" not in line
        assert "FAIL" not in line


@pytest.mark.unit
def test_format_summary_is_ascii_only():
    """A LANG=C serial console must not blow up on the last line of the run."""
    results = _all_passing() + [_witnessed("SCREEN")]
    format_summary(results, verdict=True).encode("ascii")
    bringup.format_preflight(
        bringup.Preflight(i2c_bus_present=True, config_path="/boot/config.txt")
    ).encode("ascii")


# --- Backlight ramp --------------------------------------------------------


@pytest.mark.unit
def test_backlight_duty_ramps_up_and_back_down():
    assert backlight_duty(0.0, period=2.0, ceiling=12.0) == pytest.approx(0.0)
    assert backlight_duty(1.0, period=2.0, ceiling=12.0) == pytest.approx(12.0)
    assert backlight_duty(2.0, period=2.0, ceiling=12.0) == pytest.approx(0.0)
    # Repeats, and never leaves the 0..ceiling band.
    assert backlight_duty(3.0, period=2.0, ceiling=12.0) == pytest.approx(12.0)
    for step in range(41):
        duty = backlight_duty(step / 10.0, period=2.0, ceiling=12.0)
        assert 0.0 <= duty <= 12.0


# --- Layout and rendering --------------------------------------------------

HEADLESS_DISPLAYS = [
    displays.DisplayHeadless,
    displays.DisplayHeadless176,
    displays.DisplayHeadless320,
]


@pytest.mark.unit
@pytest.mark.parametrize("display_cls", HEADLESS_DISPLAYS, ids=lambda cls: cls.__name__)
def test_grid_layout_fits_the_panel(display_cls):
    """Geometry derives from the display instance (ADR 0009), so the dashboard
    has to fit every panel without hardcoded pixel counts."""
    display = display_cls()
    layout = grid_layout(display)

    assert layout.cell > 0
    assert layout.top > display.titlebar_height
    assert layout.bottom <= display.resY
    assert layout.left >= 0
    assert layout.right <= display.resX
    # Rows are stacked in order with no overlap.
    assert len(layout.rows) == len(keypad.MATRIX_ROWS)
    for upper, lower in zip(layout.rows, layout.rows[1:]):
        assert lower.y >= upper.y + layout.cell
    assert layout.power.y >= layout.rows[-1].y + layout.cell
    # The status rows sit above the grid.
    assert layout.status.rows[bringup.STATUS_ROWS - 1] < layout.top


@pytest.mark.unit
@pytest.mark.parametrize("display_cls", HEADLESS_DISPLAYS, ids=lambda cls: cls.__name__)
def test_dashboard_renders_on_every_panel(display_cls):
    """Crash-only: composes a frame in each cell state on each panel."""
    display = display_cls()
    layout = grid_layout(display)
    grid = GridState(keypad.REV4_POPULATED)
    grid.update({(0, 0), (1, 1)})  # seen + held
    grid.update({(1, 1), (4, 0)})  # (0,0) now seen-not-held, (4,0) unexpected

    for passed in (False, True):
        dashboard = bringup.Dashboard(
            revision="rev4",
            status_lines=["IMU  ok  cal2 q+0.71", "CHG  ok  4.02V PG", "SW 13/18"],
            grid=grid,
            passed=passed,
        )
        image = bringup.draw_dashboard(display, dashboard, layout)
        assert image.size == (display.resX, display.resY)


@pytest.mark.unit
@pytest.mark.parametrize("display_cls", HEADLESS_DISPLAYS, ids=lambda cls: cls.__name__)
def test_the_hold_bar_lights_the_power_cell_progressively(display_cls):
    """The bar has to be visibly different frame to frame -- it is the only
    warning a builder gets before the card shuts down."""
    display = display_cls()
    layout = grid_layout(display)
    grid = GridState(keypad.REV4_POPULATED)
    grid.update(set(), power_closed=True)

    def power_cell(progress):
        dashboard = bringup.Dashboard(
            revision="rev4",
            status_lines=["IMU  --", "CHG  --", "SW 0/18"],
            grid=grid,
            passed=False,
            power_progress=progress,
        )
        image = bringup.draw_dashboard(display, dashboard, layout)
        assert image.size == (display.resX, display.resY)
        return image.crop(
            (
                layout.power.xs[0],
                layout.power.y,
                layout.power.xs[0] + layout.power.widths[0],
                layout.power.y + layout.cell,
            )
        ).tobytes()

    # Resting, then each of the four bar states in turn.
    frames = [power_cell(progress) for progress in (0.0, 0.01, 0.4, 0.7, 1.0)]
    assert len(set(frames)) == len(frames), "the bar does not change as it fills"


@pytest.mark.unit
@pytest.mark.parametrize("display_cls", HEADLESS_DISPLAYS, ids=lambda cls: cls.__name__)
def test_shutdown_notice_fills_the_panel(display_cls):
    """What the glass says while the card unmounts -- over SSH the session is
    about to drop, and at the bench there may be no terminal at all."""
    display = display_cls()
    image = bringup.notice_image(display, ["SHUTTING", "DOWN"])
    assert image.size == (display.resX, display.resY)
    assert image.getextrema()[0][1] > 0, "the notice rendered nothing"


@pytest.mark.unit
@pytest.mark.parametrize("display_cls", HEADLESS_DISPLAYS, ids=lambda cls: cls.__name__)
def test_pattern_images_cover_the_whole_panel(display_cls):
    display = display_cls()
    frames = bringup.pattern_images(display)
    assert len(frames) == 3
    for _, image in frames:
        assert image.size == (display.resX, display.resY)

    # The full-field frame is white everywhere -- it exists to show dead
    # pixels, so any black in it would be a bug in the pattern itself.
    _, full_field = frames[0]
    assert full_field.getextrema() == ((255, 255), (255, 255), (255, 255))

    # The stripes frame must actually contain all three channels: it is the
    # only check on the panel's channel order.
    _, stripes = frames[2]
    seen = {stripes.getpixel((x, display.resY // 2)) for x in range(display.resX)}
    assert {(255, 0, 0), (0, 255, 0), (0, 0, 255)} <= seen


@pytest.mark.unit
def test_display_choices_match_what_get_display_recognises():
    """``--display``'s choices are a hand-copy of ``displays.get_display``'s
    if-chain, because there is no registry to read.

    Guards the copy in both directions: a name bring-up offers that
    ``get_display`` would silently fall back to the SSD1351 for, and a panel
    added to ``displays.py`` that ``--display`` cannot select.
    """
    source = inspect.getsource(displays.get_display)
    recognised = set(re.findall(r'display_hardware == "([\w]+)"', source))
    assert recognised, "could not parse get_display -- update this guard"
    assert set(bringup.DISPLAY_NAMES) == recognised


@pytest.mark.unit
def test_every_revision_has_a_panel_and_a_population_map():
    """`--revision` takes its choices from `keypad.POPULATION_MAPS`, so every
    revision offered must also have a panel to open."""
    for revision in keypad.POPULATION_MAPS:
        assert revision in bringup.REVISION_PANELS
        assert bringup.REVISION_PANELS[revision] in bringup.DISPLAY_NAMES
    assert bringup.DEFAULT_REVISION in keypad.POPULATION_MAPS


@pytest.mark.unit
@pytest.mark.parametrize("display_cls", HEADLESS_DISPLAYS, ids=lambda cls: cls.__name__)
def test_rotation_composes_with_the_panels_own_orientation(display_cls):
    """`DisplaySSD1333` constructs with `rotate=3`, so `--rotate` must add to
    the panel's orientation rather than replace it -- assigning would make
    `--rotate 0` come up wrong on every rev4 board.

    It also has to drive luma's own `device.rotate` (the mechanism `main.py`
    uses for `screen_direction`): luma rotates clockwise and PIL's positive
    angles are counter-clockwise, so a hand-rolled rotate would turn the
    opposite way from the shipping app.
    """
    display = display_cls()
    display.device.rotate = 3  # stand in for the SSD1333's built-in rotation

    bringup.apply_rotation(display, 0)
    assert display.device.rotate == 3  # a no-op must not clobber it

    bringup.apply_rotation(display, 2)
    assert display.device.rotate == 1  # (3 + 2) % 4

    # And a frame still renders through luma's rotation path.
    bringup.show(display, Image.new("RGB", (display.resX, display.resY)))


# --- Import safety ---------------------------------------------------------

_BLOCKER = """
import sys

BLOCKED = ("RPi", "RPi.GPIO", "board", "rpi_hardware_pwm", "adafruit_bno055")


class Blocker:
    def find_module(self, name, path=None):
        return self if name in BLOCKED else None

    def find_spec(self, name, path=None, target=None):
        if name in BLOCKED:
            raise ImportError(f"{name} is blocked by the bring-up import test")
        return None


sys.meta_path.insert(0, Blocker())
for name in BLOCKED:
    sys.modules.pop(name, None)

import PiFinder.bringup  # noqa: E402

PiFinder.bringup.build_parser().parse_args(["--help"])
"""


@pytest.mark.unit
def test_imports_and_help_work_with_no_hardware_modules():
    """The guard that keeps every hardware import lazy.

    Runs in a subprocess with ``RPi.GPIO``, ``board``, ``rpi_hardware_pwm``
    and ``adafruit_bno055`` made unimportable, then imports the module and
    renders ``--help``. If any hardware import creeps up to module scope, this
    is what catches it -- the dev machine cannot run the tool itself.
    """
    result = subprocess.run(
        [sys.executable, "-c", _BLOCKER],
        cwd=PYTHON_DIR,
        capture_output=True,
        text=True,
    )
    # argparse's --help exits 0 after printing usage.
    assert result.returncode == 0, result.stderr
    assert "python -m PiFinder.bringup" in result.stdout
    assert "witnessed" in result.stdout
