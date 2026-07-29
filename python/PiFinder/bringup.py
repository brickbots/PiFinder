#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Bench validation for a freshly assembled PiFinder board — one command, one
screen, every listed subsystem exercised while the builder watches::

    python -m PiFinder.bringup

A **single process** that opens the panel directly, drives the keypad backlight
and buzzer, interrogates the IMU and charger, and scans the keypad matrix. It
does **not** boot the application: no ``SharedStateObj``, no catalogs, no
solver, no camera, no ``MenuManager``. It runs on a card with nothing
configured yet and is ready in about a second. Glossary:
``docs/ax/bringup/CONTEXT.md``.

Six **checks**, in three kinds — and the kind decides whether a check can gate
the **verdict**:

========= ========== ==========================================================
SCREEN    witnessed  Screen-proof patterns, then the dashboard — builder's eyes
BACKLIGHT witnessed  Continuous brightness ramp — the builder's eyes
BUZZER    witnessed  Startup earcon + one per keypress — the builder's ears
IMU       probed     BNO055 answers its chip id; the quaternion moves on tilt
CHARGER   probed     BQ25895 part-number register reads 0b111; voltages decode
SWITCHES  exercised  Every populated matrix position observed closing
========= ========== ==========================================================

Only **probed** and **exercised** checks gate the verdict and the exit status.
A witnessed check is reported as *emitted*: the program drove the hardware, and
whether light or sound came out is not something it can know.

Why the panel is not auto-detected
----------------------------------

``main.py`` and ``splash.py`` pick their panel from ``hardware_detect``, which
probes for the BQ25895 charger: charger present means a rev4 board, so use the
176x176 SSD1333. That is exactly the wrong rule for a board under bring-up — a
dead or unsoldered charger would make a perfectly good screen look dead too,
and the builder would chase the wrong fault. So bring-up takes the panel from
the revision the *builder* declares (``--revision``, default rev4 -> SSD1333)
and never from a probe result, with ``--display`` to override outright. This
deviation is deliberate and is recorded here rather than in an ADR because it
is local to this tool: nothing in the running application depends on it.

Why nothing here is translated
------------------------------

Every other user-facing string in this repo goes through ``gettext``. These
deliberately do not, and the module never performs the ``_()`` install that
``main.py`` does — adding ``_()`` calls would ``NameError`` at runtime. The
audience for a bring-up run is the **builder** at the bench, not the
**observer** at the eyepiece.

Structure follows ``sound.py``'s discipline: pure logic separated from thin
hardware seams, so the interesting parts are unit-testable off-Pi and every
hardware import is lazy. ``import PiFinder.bringup`` and
``python -m PiFinder.bringup --help`` both work with no ``RPi.GPIO``, ``board``
or ``rpi_hardware_pwm`` installed.
"""

import argparse
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Callable,
    Dict,
    FrozenSet,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeVar,
)

from PIL import Image, ImageDraw

from PiFinder import displays, keypad, utils
from PiFinder.battery_bq25895 import EXPECTED_PN, REG14
from PiFinder.keyboard_interface import KeyboardInterface as K
from PiFinder.sound import MASTER_DUTY, BuzzerPWM, play_earcon
from PiFinder.types.hardware import BatteryState
from PiFinder.types.sound import Earcon
from PiFinder.ui.layout import BoxRow, StackedRows, center_box_row, rows_below_titlebar

logger = logging.getLogger("BringUp")

T = TypeVar("T")  # a hardware seam, for Hardware._open

# --- Board / card constants -------------------------------------------------

I2C_BUS_PATH = "/dev/i2c-1"

# Raspberry Pi OS moved config.txt when the boot partition was remounted at
# /boot/firmware; look for the new location first.
BOOT_CONFIG_PATHS = ("/boot/firmware/config.txt", "/boot/config.txt")

# Which GPIO each PWM channel has to reach for its consumer to work.
BUZZER_PWM_CHANNEL = 0
BUZZER_GPIO = 12
BACKLIGHT_PWM_CHANNEL = 1
BACKLIGHT_GPIO = 13

# Legal pin/function combinations per PWM channel, from the Raspberry Pi
# `pwm` / `pwm-2chan` overlay documentation. The overlay lines name a *pin*,
# not a channel, so this table is how a config.txt line is attributed.
PWM_CHANNEL_PINS: Dict[int, FrozenSet[int]] = {
    0: frozenset({12, 18, 40, 52}),
    1: frozenset({13, 19, 41, 45, 53}),
}

BACKLIGHT_PWM_HZ = 120  # matches main.init_keypad_pwm
# main.set_keypad_brightness documents 0-100 with an effective range of ~0-12.
# That comment predates rev4 -- retune with --backlight-max if the rev4 LEDs
# behave differently.
BACKLIGHT_MAX_DUTY = 12.0
BACKLIGHT_RAMP_SECONDS = 2.0

# Loop pacing. The scan sleeps a fixed period *after* its work rather than to a
# deadline, so the real scan rate sags toward ~40 Hz on the frames that also
# redraw -- still many times faster than a human press, which is all the switch
# check needs.
SCAN_HZ = 60
DRAW_HZ = 12  # redraw slower, to keep SPI traffic reasonable
BACKLIGHT_HZ = 30  # each step is a sysfs write; 30 Hz is already imperceptible
CHARGER_POLL_SECONDS = 1.0

PATTERN_SECONDS = 1.5  # per pattern; three of them
STATUS_ROWS = 3  # IMU / CHARGER / SWITCHES lines under the title bar

DEFAULT_REVISION = "rev4"
# Panel per revision. Keyed by keypad.POPULATION_MAPS, which is where the set of
# known revisions lives -- --revision reads its choices from there, so the two
# registries cannot list different revisions. Unknown revisions fall back to the
# 128x128 panel.
REVISION_PANELS = {"rev3": "ssd1351", "rev4": "ssd1333"}
FALLBACK_PANEL = "ssd1351"
# Hand-copied from displays.get_display's if-chain (there is no registry to read
# it from). test_bringup keeps the copy honest in both directions.
DISPLAY_NAMES = (
    "ssd1333",
    "ssd1351",
    "st7789",
    "pg_128",
    "pg_176",
    "pg_320",
    "headless",
    "headless_176",
    "headless_320",
)

# Check names, so the seams and the report can't drift apart.
SCREEN = "SCREEN"
BACKLIGHT = "BACKLIGHT"
BUZZER = "BUZZER"
IMU = "IMU"
CHARGER = "CHARGER"
SWITCHES = "SWITCHES"


# ---------------------------------------------------------------------------
# Pure logic (no hardware, no sleep -- the unit-test targets)
# ---------------------------------------------------------------------------


class Kind(str, Enum):
    """What a check's answer is worth. See the glossary."""

    PROBED = "probed"  # the program asked the part directly
    EXERCISED = "exercised"  # the builder drove it, the program confirmed it
    WITNESSED = "witnessed"  # the program emitted, the builder is the sensor

    @property
    def gates(self) -> bool:
        """Whether this kind may contribute to the verdict."""
        return self in (Kind.PROBED, Kind.EXERCISED)


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    EMITTED = "emitted"  # witnessed only: the program drove the hardware
    SKIPPED = "skipped"  # could not run -- usually a failed pre-flight


@dataclass(frozen=True)
class CheckResult:
    """One named check's outcome.

    The constructor enforces the invariant the verdict rests on: a witnessed
    check can never carry PASS or FAIL, because "the buzzer passed" is not
    something the program is in a position to say.
    """

    name: str
    kind: Kind
    status: Status
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind is Kind.WITNESSED:
            if self.status not in (Status.EMITTED, Status.SKIPPED):
                raise ValueError(
                    f"witnessed check {self.name} cannot be {self.status.value}"
                )
        elif self.status is Status.EMITTED:
            raise ValueError(f"{self.kind.value} check {self.name} cannot be emitted")


def compute_verdict(results: Sequence[CheckResult]) -> bool:
    """The run's overall result: True only when every **gating** check passed.

    Witnessed checks are excluded by construction — they can only be EMITTED or
    SKIPPED, neither of which is PASS — so adding or removing them never moves
    the verdict. A gating check that was SKIPPED (a failed pre-flight
    invalidated it) does not pass either: the run did not verify that part, and
    saying PASS would claim it did. PURE.
    """
    gating = [result for result in results if result.kind.gates]
    if not gating:
        return False  # nothing was verified; that is not a pass
    return all(result.status is Status.PASS for result in gating)


def parse_pwm_overlay(config_txt: str) -> Dict[int, int]:
    """Map PWM channel -> GPIO pin, as provisioned by a ``config.txt``. PURE.

    The overlays name a pin, not a channel::

        dtoverlay=pwm,pin=13,func=4                        -> {1: 13}
        dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4  -> {0: 12, 1: 13}

    so a pin is attributed to a channel through :data:`PWM_CHANNEL_PINS`.
    A channel absent from the result is exported by the kernel but muxed to no
    pin — which is the whole reason this check exists:
    ``HardwarePWM(pwm_channel=0)`` then succeeds and drives nothing, a silence
    indistinguishable from a dead buzzer.

    Commented-out lines are ignored, and a later line for the same channel
    wins, mirroring how the firmware applies overlays in order.
    """
    routing: Dict[int, int] = {}
    for raw_line in config_txt.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line.startswith("dtoverlay="):
            continue
        fields = line[len("dtoverlay=") :].split(",")
        overlay = fields[0].strip()
        if overlay not in ("pwm", "pwm-2chan"):
            continue

        params: Dict[str, str] = {}
        for param in fields[1:]:
            if "=" in param:
                key, value = param.split("=", 1)
                params[key.strip()] = value.strip()

        # Overlay defaults: `pwm` defaults to pin 12, `pwm-2chan` to 12 and 13.
        pins = [params.get("pin", "12")]
        if overlay == "pwm-2chan":
            pins.append(params.get("pin2", "13"))

        for pin_text in pins:
            try:
                pin = int(pin_text)
            except ValueError:
                continue
            for channel, legal_pins in PWM_CHANNEL_PINS.items():
                if pin in legal_pins:
                    routing[channel] = pin
    return routing


@dataclass
class Preflight:
    """What the **card** has been provisioned with, as opposed to what the
    **board** carries.

    Reported on its own line and before anything else, because a failed
    pre-flight *invalidates* the checks that depend on it — and a
    misprovisioned image diagnosed as a bad board gets a good part desoldered.
    """

    i2c_bus_present: bool
    config_path: Optional[str]
    pwm_routing: Dict[int, int] = field(default_factory=dict)

    def _routed(self, channel: int, gpio: int) -> Optional[bool]:
        """True / False, or None when there is no config.txt to read."""
        if self.config_path is None:
            return None
        return self.pwm_routing.get(channel) == gpio

    @property
    def buzzer_routed(self) -> Optional[bool]:
        return self._routed(BUZZER_PWM_CHANNEL, BUZZER_GPIO)

    @property
    def backlight_routed(self) -> Optional[bool]:
        return self._routed(BACKLIGHT_PWM_CHANNEL, BACKLIGHT_GPIO)


def format_preflight(preflight: Preflight) -> str:
    """One line summarising the card's provisioning. PURE."""

    def routing(label: str, channel: int, gpio: int, routed: Optional[bool]) -> str:
        target = f"pwm ch{channel}->gpio{gpio} ({label})"
        if routed is None:
            return f"{target} UNKNOWN"
        return f"{target} {'ok' if routed else 'NOT ROUTED'}"

    parts = [f"i2c-1 {'ok' if preflight.i2c_bus_present else 'MISSING'}"]
    parts.append(
        routing(
            "backlight",
            BACKLIGHT_PWM_CHANNEL,
            BACKLIGHT_GPIO,
            preflight.backlight_routed,
        )
    )
    parts.append(
        routing("buzzer", BUZZER_PWM_CHANNEL, BUZZER_GPIO, preflight.buzzer_routed)
    )
    if preflight.config_path is None:
        parts.append("no config.txt found")
    return f"{'PRE-FLIGHT':<11} " + " | ".join(parts)


def read_preflight() -> Preflight:
    """Inspect the card. The only impure part is reading two files."""
    config_path: Optional[str] = None
    config_txt = ""
    for candidate in BOOT_CONFIG_PATHS:
        try:
            with open(candidate, "r") as config_file:
                config_txt = config_file.read()
            config_path = candidate
            break
        except OSError:
            continue
    return Preflight(
        i2c_bus_present=os.path.exists(I2C_BUS_PATH),
        config_path=config_path,
        pwm_routing=parse_pwm_overlay(config_txt),
    )


def backlight_duty(
    elapsed: float,
    period: float = BACKLIGHT_RAMP_SECONDS,
    ceiling: float = BACKLIGHT_MAX_DUTY,
) -> float:
    """Duty cycle (%) for the backlight ramp at ``elapsed`` seconds in. PURE.

    A triangle wave, 0 -> ceiling -> 0 every ``period``. A sweep beats a static
    level: a dim or partially-lit LED string is obvious against a ramp and
    invisible against a fixed brightness.
    """
    if period <= 0:
        return ceiling
    phase = (elapsed % period) / period
    return ceiling * (2 * phase if phase < 0.5 else 2 * (1 - phase))


Position = Tuple[int, int]


@dataclass(frozen=True)
class Edges:
    """What changed between two scans."""

    pressed: FrozenSet[Position]
    released: FrozenSet[Position]
    power_pressed: bool
    power_released: bool

    @property
    def any_pressed(self) -> bool:
        return bool(self.pressed) or self.power_pressed


class GridState:
    """Which switches have been observed closing, and which are closed now.

    Separating **held** from **seen** is deliberate. A position that reads
    permanently closed is a solder bridge; a position that closes but never
    releases is a mechanical fault. Both are build defects that a press-counter
    alone would score as a pass, and both are obvious at a glance on the grid.

    ``seen`` records raw truth, including closures at positions the population
    map says are *unpopulated* — a miswired or ghosting matrix. Those don't
    fail the run (the map, not the board, may be what is wrong) but they are
    reported, which is how a disputed population map gets settled at the bench.
    """

    def __init__(self, populated: FrozenSet[Position]):
        self.populated = frozenset(populated)
        self.seen: Set[Position] = set()
        self.held: Set[Position] = set()
        self.power_seen = False
        self.power_held = False

    def update(self, closed: Set[Position], power_closed: bool = False) -> Edges:
        """Feed one scan; return the press / release edges it produced."""
        now_closed = set(closed)
        pressed = frozenset(now_closed - self.held)
        released = frozenset(self.held - now_closed)
        self.held = now_closed
        self.seen |= now_closed

        power_pressed = power_closed and not self.power_held
        power_released = self.power_held and not power_closed
        self.power_held = power_closed
        self.power_seen = self.power_seen or power_closed

        return Edges(
            pressed=pressed,
            released=released,
            power_pressed=power_pressed,
            power_released=power_released,
        )

    @property
    def missing(self) -> FrozenSet[Position]:
        """Populated positions never observed closing."""
        return self.populated - self.seen

    @property
    def unexpected(self) -> FrozenSet[Position]:
        """Positions that closed although the population map has no switch
        there — a miswire, a ghost, or a wrong population map."""
        return frozenset(self.seen - self.populated)

    @property
    def seen_count(self) -> int:
        return len(self.populated & self.seen)

    @property
    def expected_count(self) -> int:
        return len(self.populated)

    @property
    def complete(self) -> bool:
        """Every populated switch closed at least once, power included."""
        return not self.missing and self.power_seen


# --- Labels -----------------------------------------------------------------

# One character per key, for the grid cells. ASCII on purpose: the UI fonts
# carry no box-drawing glyphs, and a builder reads these at ~10 px.
KEY_LABELS = {
    K.UP: "^",
    K.DOWN: "v",
    K.LEFT: "<",
    K.RIGHT: ">",
    K.PLUS: "+",
    K.MINUS: "-",
    K.SQUARE: "#",
}

KEY_NAMES = {
    K.PLUS: "PLUS",
    K.MINUS: "MINUS",
    K.SQUARE: "SQUARE",
    K.LEFT: "LEFT",
    K.UP: "UP",
    K.DOWN: "DOWN",
    K.RIGHT: "RIGHT",
}


def cell_label(row: int, col: int) -> str:
    """The one-character grid label for a matrix position ("" for a hole)."""
    key = keypad.key_at(row, col)
    if key == K.NA:
        return ""
    return KEY_LABELS.get(key, str(key))


def key_name(row: int, col: int) -> str:
    """The logical key a position sends, spelled out for the summary."""
    key = keypad.key_at(row, col)
    if key == K.NA:
        return "NA"
    return KEY_NAMES.get(key, str(key))


def describe_positions(positions: FrozenSet[Position], limit: int = 3) -> str:
    """``(1,3) PLUS, (4,4) SQUARE`` — positions named for the summary. PURE."""
    ordered = sorted(positions)
    shown = ", ".join(
        f"({row},{col}) {key_name(row, col)}" for row, col in ordered[:limit]
    )
    if len(ordered) > limit:
        shown += f", +{len(ordered) - limit} more"
    return shown


def format_summary(results: Sequence[CheckResult], verdict: bool) -> str:
    """The stdout report. PURE.

    ASCII only: bring-up runs over a serial console as often as not, and a
    ``LANG=C`` terminal would turn a decorative arrow into a
    ``UnicodeEncodeError`` on the very last line of the run.
    """
    lines = [
        (
            f"{result.name:<11}{result.status.value:<10}"
            f"{result.detail:<38} ({result.kind.value})"
        )
        for result in results
    ]
    lines.append(f"{'VERDICT':<11}{'PASS' if verdict else 'FAIL'}")
    return "\n".join(lines)


# --- Layout -----------------------------------------------------------------


@dataclass
class GridLayout:
    """Geometry for the switch grid, derived from the display instance (ADR
    0009) — never hardcoded, so it lays out on every panel."""

    cell: int
    gap: int
    rows: List[BoxRow]  # one per matrix row, top -> bottom
    power: BoxRow  # the power switch's own cell
    status: StackedRows  # the status text rows above the grid
    top: int
    bottom: int

    @property
    def left(self) -> int:
        return self.rows[0].xs[0]

    @property
    def right(self) -> int:
        """Right edge of a grid row."""
        row = self.rows[0]
        return row.xs[-1] + row.widths[-1]


def grid_layout(display_class: displays.DisplayBase) -> GridLayout:
    """Lay the dashboard out for ``display_class``.

    The grid takes whatever is left below the status rows, split between the
    five matrix rows and the power switch's own row, and is clamped so it can
    never run off either edge.
    """
    fonts = display_class.fonts
    gap = max(2, fonts.base.height // 4)
    status = rows_below_titlebar(display_class, font=fonts.small, gap=gap)

    n_cols = len(keypad.MATRIX_COLS)
    n_rows = len(keypad.MATRIX_ROWS)
    stacked = n_rows + 1  # matrix rows + the power switch's row

    top = status.top + STATUS_ROWS * status.pitch + gap
    by_height = (display_class.resY - top - stacked * gap) // stacked
    by_width = (display_class.resX - (n_cols + 1) * gap) // n_cols
    cell = max(1, min(by_height, by_width))

    rows = [
        center_box_row(
            display_class, [cell] * n_cols, gap, top + index * (cell + gap), cell
        )
        for index in range(n_rows)
    ]
    power_y = top + n_rows * (cell + gap)
    power = center_box_row(display_class, [cell * 3 + gap * 2], gap, power_y, cell)
    return GridLayout(
        cell=cell,
        gap=gap,
        rows=rows,
        power=power,
        status=status,
        top=top,
        bottom=power_y + cell,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def pattern_images(
    display_class: displays.DisplayBase,
) -> List[Tuple[str, Image.Image]]:
    """The witnessed screen-proof sequence. PURE (builds images; draws nothing
    to hardware).

    Three patterns, because the dashboard alone can reveal none of this:

    1. **full field** — dead pixels and uniformity;
    2. **extent** — a 1 px border, corner ticks, an asymmetric top-left block
       and a centre cross: offset, rotation and clipped edges;
    3. **RGB stripes** — channel order, which catches a wrong ``bgr`` flag or
       the wrong panel part.

    These draw raw RGB, deliberately bypassing the red ``Colors`` mask: the
    point is to prove all three channels reach the glass, even though the
    product only ever shows red.
    """
    width, height = display_class.resX, display_class.resY
    white = (255, 255, 255)
    frames: List[Tuple[str, Image.Image]] = []

    frames.append(("full field", Image.new("RGB", (width, height), white)))

    extent = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(extent)
    draw.rectangle([0, 0, width - 1, height - 1], outline=white)
    tick = max(3, min(width, height) // 10)
    # Corner ticks, inset by a pixel so they read separately from the border.
    for x_edge in (1, width - 2 - tick):
        for y_edge in (1, height - 2 - tick):
            draw.rectangle(
                [x_edge, y_edge, x_edge + tick, y_edge + tick], outline=white
            )
    # A solid block in the top-left corner only: the asymmetry is what makes a
    # rotated or mirrored panel obvious at a glance.
    draw.rectangle([1, 1, 1 + tick, 1 + tick], fill=white)
    draw.line([width // 2, 0, width // 2, height - 1], fill=white)
    draw.line([0, height // 2, width - 1, height // 2], fill=white)
    frames.append(("extent", extent))

    stripes = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(stripes)
    band = width / 3.0
    for index, color in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255))):
        draw.rectangle(
            [round(index * band), 0, round((index + 1) * band) - 1, height - 1],
            fill=color,
        )
    frames.append(("rgb stripes", stripes))

    return frames


@dataclass
class Dashboard:
    """Everything the live screen renders."""

    revision: str
    status_lines: List[str]
    grid: GridState
    passed: bool


def _text_width(font, text: str) -> int:
    return font.width * len(text)


def _draw_cell(
    draw: ImageDraw.ImageDraw,
    display_class: displays.DisplayBase,
    x: int,
    y: int,
    width: int,
    height: int,
    label: str,
    populated: bool,
    seen: bool,
    held: bool,
) -> None:
    """One switch cell, in whichever of the four states it is in.

    Shared by the matrix grid and the power switch's own (wider) cell, so a
    restyle of the states can never drift between the two.
    """
    colors = display_class.colors
    if not populated and not seen:
        return

    box = [x, y, x + width - 1, y + height - 1]
    if held:
        draw.rectangle(box, fill=colors.get(255))
        ink = (0, 0, 0)
    elif seen:
        draw.rectangle(box, outline=colors.get(255))
        ink = colors.get(255)
    else:
        draw.rectangle(box, outline=colors.get(64))
        ink = colors.get(96)

    if not populated:
        label = label or "?"  # an unexpected closure, flagged rather than hidden
    if not label:
        return
    font = display_class.fonts.small
    draw.text(
        (x + (width - _text_width(font, label)) // 2, y + (height - font.height) // 2),
        label,
        font=font.font,
        fill=ink,
    )


def draw_dashboard(
    display_class: displays.DisplayBase, dashboard: Dashboard, layout: GridLayout
) -> Image.Image:
    """Compose the live screen: title bar, status rows, switch grid."""
    colors = display_class.colors
    fonts = display_class.fonts
    image = Image.new("RGB", (display_class.resX, display_class.resY), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    titlebar = display_class.titlebar_height

    # The title bar inverts on a passing verdict, so the result is readable
    # from across the bench without reading any text.
    if dashboard.passed:
        draw.rectangle([0, 0, display_class.resX, titlebar - 1], fill=colors.get(255))
        title, ink = "PASS", (0, 0, 0)
    else:
        draw.line(
            [0, titlebar - 1, display_class.resX, titlebar - 1], fill=colors.get(128)
        )
        title, ink = "BRING-UP", colors.get(255)
    title_y = max(0, (titlebar - fonts.bold.height) // 2)
    draw.text((2, title_y), title, font=fonts.bold.font, fill=ink)
    draw.text(
        (display_class.resX - 2 - _text_width(fonts.base, dashboard.revision), title_y),
        dashboard.revision,
        font=fonts.base.font,
        fill=ink,
    )

    for index, line in enumerate(dashboard.status_lines[:STATUS_ROWS]):
        draw.text(
            (2, layout.status.rows[index]),
            line,
            font=fonts.small.font,
            fill=colors.get(192),
        )

    grid = dashboard.grid
    for row_index, box_row in enumerate(layout.rows):
        for col_index, x in enumerate(box_row.xs):
            position = (row_index, col_index)
            _draw_cell(
                draw,
                display_class,
                x,
                box_row.y,
                layout.cell,
                layout.cell,
                cell_label(row_index, col_index),
                populated=position in grid.populated,
                seen=position in grid.seen,
                held=position in grid.held,
            )

    # The power switch is wired to its own line rather than into the matrix, so
    # it gets its own wider cell -- but the same four states.
    _draw_cell(
        draw,
        display_class,
        layout.power.xs[0],
        layout.power.y,
        layout.power.widths[0],
        layout.cell,
        "PWR",
        populated=True,
        seen=grid.power_seen,
        held=grid.power_held,
    )

    return image


def apply_rotation(display_class: displays.DisplayBase, quarter_turns: int) -> None:
    """Turn the panel by ``quarter_turns``, the way the app does.

    Bring-up ignores the user config entirely (a board under bring-up has none
    yet), so ``--rotate`` is how a Bloom / Heart build gets a readable
    dashboard. It drives luma's own ``device.rotate`` — the same mechanism
    ``main.py`` uses for ``screen_direction`` — rather than rotating the
    composed image with PIL. Two reasons: PIL's positive rotation is
    counter-clockwise while luma's is clockwise, so a hand-rolled version would
    turn the *opposite* way from the shipping app for odd quarter-turns; and it
    keeps rotation out of the per-frame path.

    Composed, not assigned: ``DisplaySSD1333`` already constructs with
    ``rotate=3``, so assigning would silently discard the panel's own
    orientation and make ``--rotate 0`` come up wrong on every rev4 board.
    """
    if quarter_turns:
        device = display_class.device
        device.rotate = (device.rotate + quarter_turns) % 4


def show(display_class: displays.DisplayBase, image: Image.Image) -> None:
    """Push a frame to the panel."""
    display_class.device.display(image.convert(display_class.device.mode))


# ---------------------------------------------------------------------------
# Hardware seams (constructed only on real hardware; every import is lazy)
# ---------------------------------------------------------------------------


class BacklightPWM:
    """Thin wrapper over ``rpi_hardware_pwm`` channel 1, driving the keypad
    backlight LEDs. Mirrors ``sound.BuzzerPWM`` on channel 0.

    ``main.init_keypad_pwm`` / ``set_keypad_brightness`` do the same job, but
    depend on a ``HardwarePWM`` global imported inside main's ``__main__``
    block, so they cannot be imported here. This seam is a candidate answer to
    the standing TODO at ``main.py:78``; adopting it there is out of scope.
    """

    def __init__(self, hz: int = BACKLIGHT_PWM_HZ):
        from rpi_hardware_pwm import HardwarePWM

        self._pwm = HardwarePWM(pwm_channel=BACKLIGHT_PWM_CHANNEL, hz=hz)
        self._pwm.start(0)

    def set(self, duty: float) -> None:
        self._pwm.change_duty_cycle(max(0.0, min(100.0, duty)))

    def stop(self) -> None:
        self._pwm.stop()


class MatrixScanner:
    """Raw keypad matrix scan: drive one row LOW as an output, read all the
    columns (pull-ups, so a closed switch reads LOW), restore the row to input.

    Mirrors ``KeyboardPi.run_keyboard``'s technique but deliberately keeps none
    of its interpretation — no debounce beyond the frame, no chording, no
    long-press, no auto-repeat. Bring-up wants the raw edge: every one of those
    behaviours can mask a faulty switch.
    """

    def __init__(self) -> None:
        import RPi.GPIO as GPIO

        self._gpio = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(keypad.MATRIX_ROWS, GPIO.IN)
        GPIO.setup(keypad.MATRIX_COLS, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # The power line has its own pull-up in hardware.
        GPIO.setup(keypad.POWER_GPIO, GPIO.IN)

    def scan(self) -> Set[Position]:
        gpio = self._gpio
        closed: Set[Position] = set()
        for row_index, row_pin in enumerate(keypad.MATRIX_ROWS):
            gpio.setup(row_pin, gpio.OUT, initial=gpio.LOW)
            for col_index, col_pin in enumerate(keypad.MATRIX_COLS):
                if gpio.input(col_pin) == gpio.LOW:
                    closed.add((row_index, col_index))
            gpio.setup(row_pin, gpio.IN)
        return closed

    def power_closed(self) -> bool:
        """The power switch, read directly and active low.

        Never acted on: no shutdown, no jump to a label, and nothing anywhere
        near GPIO14. Pressing power during a bring-up run only lights a cell —
        and there is no 1 s hold requirement, so a brief tap is enough, which
        also keeps the press short in case the LTC2954 kills on a long hold.
        """
        return not self._gpio.input(keypad.POWER_GPIO)

    def stop(self) -> None:
        self._gpio.cleanup()


class ImuProbe:
    """Wraps ``imu_pi.Imu``.

    ``adafruit_bno055``'s constructor reads and validates the BNO055 chip id
    and raises on mismatch, so **construction succeeding is the comms proof**.
    The live quaternion is the second half: a part that ACKs but sits in a bad
    mode would pass a bare presence probe and never move the numbers.
    """

    def __init__(self) -> None:
        from PiFinder.imu_pi import Imu

        self._imu = Imu()
        self.calibration = 0
        self.quaternion: Optional[Tuple[float, ...]] = None
        self.saw_quaternion = False
        self.error: Optional[str] = None

    def update(self) -> None:
        try:
            self._imu.update()
        except (OSError, RuntimeError) as exc:  # transient I2C trouble
            self.error = str(exc)
            return
        self.error = None
        self.calibration = self._imu.calibration
        quat = self._imu.avg_quat
        # Imu initialises avg_quat to (0, 0, 0, 0) and leaves it there while
        # calibration is 0, so an all-zero quaternion means "nothing measured
        # yet", not "measured zero" -- treating it as live would let a chip
        # that ACKs but never fuses pass the check.
        if quat and quat[0] is not None and any(value != 0 for value in quat):
            self.quaternion = tuple(quat)
            self.saw_quaternion = True


class ChargerProbe:
    """Wraps ``battery_bq25895.BQ25895``.

    **Strictly read-only.** ``read_state()``'s one-shot ADC trigger is the only
    sanctioned write (ADR 0006); ``apply_charging_config()`` is never called —
    setting charge current belongs to the monitor process (ADR 0017), not to a
    diagnostic. The part-number register check is a stronger identity proof
    than the bare bus ACK ``hardware_detect`` uses, and the right depth here.
    """

    def __init__(self) -> None:
        from PiFinder.battery_bq25895 import BQ25895

        self._chip = BQ25895()
        self.part_number = (self._chip.read_reg(REG14) >> 3) & 0b111
        self.identified = self.part_number == EXPECTED_PN
        self.state: Optional[BatteryState] = None
        self.error: Optional[str] = None

    def read(self) -> None:
        try:
            self.state = self._chip.read_state()
        except (OSError, RuntimeError) as exc:
            self.error = str(exc)


class Hardware:
    """Every seam a run drives, opened best-effort.

    A seam that will not open records why and leaves the rest of the run
    working: a board whose charger is dead must still bring its screen up and
    still let the builder sweep the keypad.

    Two reasons a seam can be absent, kept apart because they mean different
    things to the builder: ``skips`` is the card's fault (a failed pre-flight
    invalidated the check) and ``failures`` is the board's.
    """

    def __init__(self) -> None:
        self.backlight: Optional[BacklightPWM] = None
        self.buzzer: Optional[BuzzerPWM] = None
        self.scanner: Optional[MatrixScanner] = None
        self.imu: Optional[ImuProbe] = None
        self.charger: Optional[ChargerProbe] = None
        self.failures: Dict[str, str] = {}
        self.skips: Dict[str, str] = {}

    def open(self, preflight: Preflight) -> None:
        if preflight.backlight_routed is False:
            self.skips[BACKLIGHT] = (
                f"pwm ch{BACKLIGHT_PWM_CHANNEL} not routed to gpio{BACKLIGHT_GPIO}"
            )
        else:
            self.backlight = self._open(BACKLIGHT, BacklightPWM)

        if preflight.buzzer_routed is False:
            self.skips[BUZZER] = (
                f"pwm ch{BUZZER_PWM_CHANNEL} not routed to gpio{BUZZER_GPIO}"
            )
        else:
            self.buzzer = self._open(BUZZER, BuzzerPWM)

        self.scanner = self._open(SWITCHES, MatrixScanner)

        if not preflight.i2c_bus_present:
            reason = f"no {I2C_BUS_PATH} (see pre-flight)"
            self.skips[IMU] = reason
            self.skips[CHARGER] = reason
        else:
            self.imu = self._open(IMU, ImuProbe)
            self.charger = self._open(CHARGER, ChargerProbe)

    def _open(self, name: str, build: Callable[[], T]) -> Optional[T]:
        """Build one seam, or record why it would not open and carry on."""
        try:
            return build()
        except Exception as exc:  # noqa: BLE001 - any failure is just a reason
            self.failures[name] = f"{type(exc).__name__}: {exc}"
            logger.debug("bring-up: %s unavailable: %s", name, exc)
            return None

    def absent_reason(self, name: str) -> str:
        return self.skips.get(name) or self.failures.get(name, "unavailable")

    def absent_status(self, name: str) -> Status:
        """A gating check the card invalidated was SKIPPED; one the board
        failed to answer FAILED."""
        return Status.SKIPPED if name in self.skips else Status.FAIL

    def close(self) -> None:
        """Silence the buzzer, darken the backlight, release the GPIOs.

        Called from a ``finally`` on every exit path including SIGINT / SIGTERM:
        the buzzer must never be left driven.
        """
        for seam in (self.buzzer, self.backlight, self.scanner):
            if seam is None:
                continue
            try:
                seam.stop()
            except Exception:  # noqa: BLE001 - cleanup is best-effort
                logger.debug("bring-up: cleanup failed", exc_info=True)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def imu_line(hardware: Hardware) -> str:
    """The IMU status row."""
    probe = hardware.imu
    if probe is None:
        return f"IMU  --  {hardware.absent_reason(IMU)}"
    if probe.quaternion is None:
        return f"IMU  ok  cal{probe.calibration} q ----"
    return f"IMU  ok  cal{probe.calibration} q{probe.quaternion[0]:+.2f}"


def charger_line(hardware: Hardware) -> str:
    """The charger status row."""
    probe = hardware.charger
    if probe is None:
        return f"CHG  --  {hardware.absent_reason(CHARGER)}"
    identity = "ok" if probe.identified else "BAD"
    state = probe.state
    if state is None or state.battery_voltage is None:
        return f"CHG  {identity}  ----V"
    source = "PG" if state.on_external_power else "BAT"
    return f"CHG  {identity}  {state.battery_voltage:.2f}V {source}"


def switch_line(grid: GridState) -> str:
    """The switch status row."""
    power = "*" if grid.power_seen else "."
    return f"SW   {grid.seen_count}/{grid.expected_count}      PWR {power}"


def absent_result(hardware: Hardware, name: str, kind: Kind) -> CheckResult:
    """The check for a seam that never opened.

    A witnessed check is always SKIPPED and never FAILED — the program is not
    the sensor, so it has nothing to fail. A gating check distinguishes the two
    reasons: the card invalidated it (SKIPPED) or the board would not answer
    (FAIL). Encoding that here rather than at five call sites is what keeps the
    witnessed rule from being re-derived by hand each time.
    """
    status = Status.SKIPPED if kind is Kind.WITNESSED else hardware.absent_status(name)
    return CheckResult(name, kind, status, hardware.absent_reason(name))


def switches_detail(grid: GridState) -> str:
    """What the switch sweep found, in one line. PURE."""
    detail = f"{grid.seen_count}/{grid.expected_count}"
    if not grid.power_seen:
        detail += " - PWR never closed"
    if grid.missing:
        detail += f" - {describe_positions(grid.missing)} never closed"
    if grid.unexpected:
        # Not a failure -- the population map, not the board, may be what is
        # wrong -- but never silently dropped.
        detail += f" - unexpected: {describe_positions(grid.unexpected)}"
    return detail


def build_results(
    hardware: Hardware,
    grid: GridState,
    pattern_count: int,
    backlight_max: float,
) -> List[CheckResult]:
    """Turn the run's observations into the six checks. PURE given its inputs."""
    results = [
        CheckResult(
            SCREEN,
            Kind.WITNESSED,
            Status.EMITTED,
            f"{pattern_count} patterns + dashboard"
            if pattern_count
            else "dashboard only",
        )
    ]

    if hardware.backlight is None:
        results.append(absent_result(hardware, BACKLIGHT, Kind.WITNESSED))
    else:
        results.append(
            CheckResult(
                BACKLIGHT,
                Kind.WITNESSED,
                Status.EMITTED,
                f"ramp 0-{backlight_max:g}% on pwm ch{BACKLIGHT_PWM_CHANNEL}",
            )
        )

    if hardware.buzzer is None:
        results.append(absent_result(hardware, BUZZER, Kind.WITNESSED))
    else:
        results.append(
            CheckResult(
                BUZZER, Kind.WITNESSED, Status.EMITTED, "startup + keypress earcons"
            )
        )

    if hardware.imu is None:
        results.append(absent_result(hardware, IMU, Kind.PROBED))
    else:
        live = hardware.imu.saw_quaternion
        results.append(
            CheckResult(
                IMU,
                Kind.PROBED,
                Status.PASS if live else Status.FAIL,
                f"BNO055 id ok, cal {hardware.imu.calibration}, "
                f"{'q live' if live else 'no quaternion'}",
            )
        )

    if hardware.charger is None:
        results.append(absent_result(hardware, CHARGER, Kind.PROBED))
    else:
        probe = hardware.charger
        voltage = ""
        if probe.state is not None and probe.state.battery_voltage is not None:
            source = "PG" if probe.state.on_external_power else "BAT"
            voltage = f", {probe.state.battery_voltage:.2f}V, {source}"
        results.append(
            CheckResult(
                CHARGER,
                Kind.PROBED,
                Status.PASS if probe.identified else Status.FAIL,
                f"BQ25895 pn=0b{probe.part_number:03b}{voltage}",
            )
        )

    if hardware.scanner is None:
        results.append(absent_result(hardware, SWITCHES, Kind.EXERCISED))
    else:
        results.append(
            CheckResult(
                SWITCHES,
                Kind.EXERCISED,
                Status.PASS if grid.complete else Status.FAIL,
                switches_detail(grid),
            )
        )

    return results


def run_patterns(
    display_class: displays.DisplayBase,
    frames: List[Tuple[str, Image.Image]],
    args: argparse.Namespace,
) -> None:
    """Play the screen-proof sequence, once or forever."""
    while True:
        for name, image in frames:
            logger.debug("bring-up: pattern %s", name)
            show(display_class, image)
            time.sleep(PATTERN_SECONDS)
        if not args.pattern_loop:
            return


def run_loop(
    display_class: displays.DisplayBase,
    args: argparse.Namespace,
    hardware: Hardware,
    grid: GridState,
    pattern_count: int,
) -> None:
    """Scan, drive and redraw until Ctrl-C (or ``--timeout``)."""
    layout = grid_layout(display_class)

    def draw() -> None:
        dashboard = Dashboard(
            revision=args.revision,
            status_lines=[
                imu_line(hardware),
                charger_line(hardware),
                switch_line(grid),
            ],
            grid=grid,
            # The banner and the exit status come from the same function, so
            # the screen can never disagree with the printed summary.
            passed=compute_verdict(
                build_results(hardware, grid, pattern_count, args.backlight_max)
            ),
        )
        show(display_class, draw_dashboard(display_class, dashboard, layout))

    # Put the dashboard up before the startup earcon, so the panel isn't left
    # holding the last pattern frame for the half-second the cue takes.
    draw()
    if hardware.buzzer is not None:
        play_earcon(hardware.buzzer, Earcon.STARTUP, args.volume)

    started = time.monotonic()
    last_draw = time.monotonic()
    last_charger = 0.0
    last_backlight = 0.0

    while True:
        now = time.monotonic()
        if args.timeout and now - started >= args.timeout:
            return

        if hardware.scanner is not None:
            edges = grid.update(
                hardware.scanner.scan(), hardware.scanner.power_closed()
            )
            if edges.any_pressed and hardware.buzzer is not None:
                # Re-proves the buzzer once per closure -- ~18 times over a
                # full keypad sweep.
                play_earcon(hardware.buzzer, Earcon.KEYPRESS, args.volume)

        # Each step is an open/write/close on a sysfs file, so step the ramp
        # well below the scan rate; the eye cannot tell the difference.
        if (
            hardware.backlight is not None
            and now - last_backlight >= 1.0 / BACKLIGHT_HZ
        ):
            hardware.backlight.set(
                backlight_duty(now - started, ceiling=args.backlight_max)
            )
            last_backlight = now

        if hardware.imu is not None:
            hardware.imu.update()  # self-throttles to the IMU sample rate

        if hardware.charger is not None and now - last_charger >= CHARGER_POLL_SECONDS:
            hardware.charger.read()
            last_charger = now

        if now - last_draw >= 1.0 / DRAW_HZ:
            draw()
            last_draw = now

        time.sleep(1.0 / SCAN_HZ)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m PiFinder.bringup",
        description=(
            "Bench validation for a freshly assembled PiFinder board: screen, "
            "keypad backlight, buzzer, IMU, charger and every switch, on one "
            "live screen. Stop the pifinder service first."
        ),
        epilog=(
            "The verdict covers the probed (IMU, CHARGER) and exercised "
            "(SWITCHES) checks only; SCREEN / BACKLIGHT / BUZZER are witnessed "
            "-- you are the sensor. Exit status is 0 when the verdict passes."
        ),
    )
    parser.add_argument(
        "--revision",
        # Read from the population maps, so the revisions bring-up offers and
        # the revisions it has a switch map for cannot diverge.
        choices=sorted(keypad.POPULATION_MAPS),
        default=DEFAULT_REVISION,
        help=(
            "Board revision being brought up. Sets the switch population map "
            "(rev3: 17 switches, rev4: 18) and the default panel. Default: rev4"
        ),
    )
    parser.add_argument(
        "--display",
        choices=DISPLAY_NAMES,
        default=None,
        help=(
            "Panel to open. Defaults to the revision's panel (rev4: ssd1333, "
            "rev3: ssd1351) -- never derived from a hardware probe, so a dead "
            "charger cannot make a good screen look dead."
        ),
    )
    parser.add_argument(
        "--rotate",
        type=int,
        choices=(0, 1, 2, 3),
        default=0,
        help=(
            "Quarter-turns to rotate the screen, added to the panel's own "
            "orientation. Bloom / Heart builds (the app's 'as_bloom' / "
            "'as_heart' screen_direction) want 2."
        ),
    )
    parser.add_argument(
        "--no-patterns",
        action="store_true",
        help="Skip the screen-proof patterns and go straight to the dashboard",
    )
    parser.add_argument(
        "--pattern-loop",
        action="store_true",
        help="Loop the patterns forever (panel-only work); Ctrl-C to stop",
    )
    parser.add_argument(
        "--backlight-max",
        type=float,
        default=BACKLIGHT_MAX_DUTY,
        help=(
            f"Peak duty %% of the backlight ramp (default {BACKLIGHT_MAX_DUTY:g}; "
            "main.py documents ~0-12 as the effective range on rev3)"
        ),
    )
    parser.add_argument(
        "--volume",
        choices=sorted(MASTER_DUTY),
        default="5",
        help="Buzzer master volume for the earcons (default 5)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="End the run after SECONDS instead of waiting for Ctrl-C",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.display is None:
        args.display = REVISION_PANELS.get(args.revision, FALLBACK_PANEL)

    logging.basicConfig(level=logging.WARNING)

    # Refuse to run while the service holds the panel, the PWM channels and the
    # I2C bus -- otherwise the screen garbles and every reading is suspect.
    if not utils.acquire_single_instance_lock():
        print(
            "Another PiFinder instance is running. Stop the service first:\n"
            "  sudo systemctl stop pifinder"
        )
        return 1

    def _terminate(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _terminate)

    preflight = read_preflight()
    # Printed up front as well as in the summary: a builder should not spend
    # five minutes wondering why the buzzer is silent.
    print(format_preflight(preflight))

    display_class = displays.get_display(args.display)
    apply_rotation(display_class, args.rotate)
    hardware = Hardware()
    hardware.open(preflight)
    grid = GridState(keypad.POPULATION_MAPS[args.revision])

    frames = [] if args.no_patterns else pattern_images(display_class)
    pattern_count = len(frames)
    try:
        if frames:
            run_patterns(display_class, frames, args)
        # The frames are only needed while they are being shown; a full-panel
        # RGB image each is ~90 KB, and the dashboard run is open-ended.
        frames = []
        run_loop(display_class, args, hardware, grid, pattern_count)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        hardware.close()
        try:
            blank = Image.new("RGB", (display_class.resX, display_class.resY))
            show(display_class, blank)
        except Exception:  # noqa: BLE001 - blanking is best-effort
            logger.debug("bring-up: could not blank the panel", exc_info=True)

    results = build_results(hardware, grid, pattern_count, args.backlight_max)
    verdict = compute_verdict(results)
    print()
    print(format_preflight(preflight))
    print(format_summary(results, verdict))
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
