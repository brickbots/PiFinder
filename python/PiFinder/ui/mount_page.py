"""The mount page of Object Details: a live status band and a map of the
keypad, with each mount function drawn where its key is.

    7 Sync   8 N    9 Step+
    4 W      5 GOTO 6 E
    1 Init   2 S    3 Step-
         0 STOP (full width)

The geometry comes from the display resolution and the font metrics, so the
page fits the 128, 176 and 320 pixel screens.
"""

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from PiFinder.cat_images import cardinal_vectors
from PiFinder.types.mount import DISTANCE_PHASES, MountStatus, format_step

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


# Nerd Font (Font Awesome) icons in the PiFinder fonts.
ICON_UP = ""
ICON_DOWN = ""
ICON_LEFT = ""
ICON_RIGHT = ""
ICON_GOTO = ""
ICON_SYNC = ""
ICON_INIT = ""
ICON_PLUS = ""
ICON_MINUS = ""
ICON_STOP = ""

ICON_SETTINGS = "\uf013"

# Keys of the connection screen.
CONNECT_KEY = 1
SETTINGS_KEY = 2

# The direction keys: number key -> screen direction (x right, y down).
ARROW_KEYS = {8: (0.0, -1.0), 2: (0.0, 1.0), 4: (-1.0, 0.0), 6: (1.0, 0.0)}
ARROW_ICONS = {8: ICON_UP, 2: ICON_DOWN, 4: ICON_LEFT, 6: ICON_RIGHT}

# Key -> (row, column) on the keypad. 0 spans the bottom row.
KEY_CELLS = {
    7: (0, 0),
    8: (0, 1),
    9: (0, 2),
    4: (1, 0),
    5: (1, 1),
    6: (1, 2),
    1: (2, 0),
    2: (2, 1),
    3: (2, 2),
}
STOP_KEY = 0
# How long a pressed key shows inverted (seconds).
PRESS_FLASH_S = 0.35
# How long the cells show their key numbers after the page opens (seconds).
KEY_NUMBERS_S = 2.0

# Phases without a connected mount: key 1 connects, the move keys are dim.
_UNCONNECTED_PHASES = ("MOUNT_UNKNOWN", "MOUNT_INIT_TELESCOPE")
# Keys that need a connected mount.
_MOVE_KEYS = (2, 3, 4, 5, 6, 7, 8, 9, 0)

# Phases that move the mount: the distance bar shows the progress.
_MOVING_PHASES = ("MOUNT_TARGET_ACQUISITION_MOVE", "MOUNT_TARGET_ACQUISITION_REFINE")


def key_labels(
    connected: bool = True, letters: Optional[dict[int, str]] = None
) -> dict[int, tuple[str, str]]:
    """Key -> (icon, label). The labels are short: a cell is about 40 px.
    ``letters`` is the compass point each direction key moves to now."""
    letters = letters or {8: _("N"), 2: _("S"), 4: _("W"), 6: _("E")}
    return {
        7: (ICON_SYNC, _("Sync")),
        8: (ICON_UP, letters[8]),
        9: (ICON_PLUS, _("Step")),
        4: (ICON_LEFT, letters[4]),
        5: (ICON_GOTO, _("GOTO")),
        6: (ICON_RIGHT, letters[6]),
        1: (ICON_INIT, _("Init") if connected else _("Connect")),
        2: (ICON_DOWN, letters[2]),
        3: (ICON_MINUS, _("Step")),
        STOP_KEY: (ICON_STOP, _("STOP")),
    }


@dataclass
class MountPageState:
    """What the page remembers between frames."""

    pressed_key: Optional[int] = None
    pressed_at: float = 0.0
    # When the page opened: the cells show their key numbers for a moment.
    opened_at: float = 0.0
    # The direction key whose arrow is held down (a continuous move).
    held_key: Optional[int] = None
    # The largest distance of the current slew, for the progress bar.
    slew_start_distance: Optional[float] = None
    last_phase: str = field(default="")

    def press(self, key: int, now: Optional[float] = None) -> None:
        self.pressed_key = key
        self.pressed_at = time.time() if now is None else now

    def flashing(self, key: int, now: float) -> bool:
        if self.held_key == key:
            return True
        return self.pressed_key == key and now - self.pressed_at < PRESS_FLASH_S

    def open(self, now: Optional[float] = None) -> None:
        self.opened_at = time.time() if now is None else now

    def showing_numbers(self, now: float) -> bool:
        return now - self.opened_at < KEY_NUMBERS_S


def sky_directions(
    mode: str, roll: Optional[float], flip: bool, flop: bool
) -> dict[int, tuple[float, float]]:
    """For each direction key, the move on the sky as (north, east) parts.

    "eyepiece": a key moves towards what is in that direction of the
    eyepiece view (8 brings the sky at the top of the view to the centre).
    The view is the POSS image orientation of Object Details: 180° plus the
    solve roll, then the telescope's flip and flop (ADR 0003).
    "compass", or no roll yet: north up and east left.
    """
    if mode == "eyepiece" and roll is not None:
        n, e = cardinal_vectors(180.0 + roll, -1 if flop else 1, -1 if flip else 1)
    else:
        n, e = (0.0, -1.0), (-1.0, 0.0)
    return {
        key: (dx * n[0] + dy * n[1], dx * e[0] + dy * e[1])
        for key, (dx, dy) in ARROW_KEYS.items()
    }


def compass_letter(north: float, east: float) -> str:
    """The compass point nearest to a (north, east) move."""
    if abs(north) >= abs(east):
        return _("N") if north > 0 else _("S")
    return _("E") if east > 0 else _("W")


def is_connected(status: Optional[MountStatus], now: Optional[float] = None) -> bool:
    """True when the mount process has a connected mount: the page shows
    the keypad map, else the connection screen."""
    now = time.time() if now is None else now
    return (
        status is not None
        and not status.is_stale(now)
        and status.phase not in _UNCONNECTED_PHASES
    )


@dataclass(frozen=True)
class MountSetup:
    """The configured mount, for the connection screen."""

    model: str
    connection: str
    port: str
    baud: int
    address: str

    def link_text(self) -> str:
        if self.connection == "wifi":
            return _("WiFi") + " " + (self.address or _("driver default"))
        port = self.port.rsplit("/", 1)[-1]
        return f"USB {port} {self.baud}"


def _wrap(text: str, font, width: int, lines: int) -> list[str]:
    """Split text into at most ``lines`` lines of ``width`` pixels."""
    chars = max(1, width // max(font.width, 1))
    out: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if len(candidate) <= chars:
            line = candidate
            continue
        out.append(line)
        line = word
    if line:
        out.append(line)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = _fit(out[-1] + " …", font, width)
    return [_fit(x, font, width) for x in out]


def _fit(text: str, font, width: int) -> str:
    """Cut text to the width in pixels (the fonts are monospaced)."""
    chars = max(1, width // max(font.width, 1))
    return text if len(text) <= chars else text[: chars - 1] + "…"


def _centered(draw, box, text: str, font, fill) -> None:
    x0, y0, x1, y1 = box
    width = draw.textlength(text, font=font.font)
    draw.text(
        (x0 + (x1 - x0 - width) / 2, y0 + (y1 - y0 - font.height) / 2),
        text,
        font=font.font,
        fill=fill,
    )


def _status_texts(
    status: Optional[MountStatus], now: float
) -> tuple[str, str, str, bool, bool]:
    """(phase, distance, detail, live, connected) for the status band."""
    if status is None or status.is_stale(now):
        return _("NO STATUS"), "", _("No answer yet"), False, False
    if status.phase == "MOUNT_UNKNOWN":
        detail = status.error or _("Press 1 to connect")
        return _("NOT CONNECTED"), "", detail, True, False
    if status.phase == "MOUNT_INIT_TELESCOPE":
        return _("CONNECTING"), "", status.model, True, False
    distance = ""
    if status.distance_deg is not None and status.phase in DISTANCE_PHASES:
        distance = format_step(status.distance_deg)
    detail = _("step") + " " + format_step(status.step_deg)
    return status.text.upper(), distance, detail, True, True


def _progress(state: MountPageState, status: Optional[MountStatus]) -> Optional[float]:
    """The slew progress 0..1, or None when the mount does not slew."""
    if status is None or status.phase not in _MOVING_PHASES:
        state.slew_start_distance = None
        return None
    if status.distance_deg is None:
        return None
    if status.phase != state.last_phase or state.slew_start_distance is None:
        state.slew_start_distance = status.distance_deg
    state.slew_start_distance = max(state.slew_start_distance, status.distance_deg)
    if state.slew_start_distance <= 0:
        return 1.0
    return 1.0 - status.distance_deg / state.slew_start_distance


def draw_mount_page(
    draw,
    display_class,
    fonts,
    colors,
    status: Optional[MountStatus],
    state: MountPageState,
    now: Optional[float] = None,
    letters: Optional[dict[int, str]] = None,
) -> None:
    now = time.time() if now is None else now
    width = display_class.resX
    height = display_class.resY
    top = display_class.titlebar_height + 2
    bright, mid, dim, faint = (
        colors.get(255),
        colors.get(160),
        colors.get(96),
        colors.get(40),
    )

    # Status band: the phase and the distance, then the step.
    phase, distance, detail, live, connected = _status_texts(status, now)
    # A margin of 2 px: textlength cuts the right edge of some glyphs.
    distance_w = (
        int(draw.textlength(distance, font=fonts.bold.font)) + 2 if distance else 0
    )
    draw.text(
        (0, top),
        _fit(phase, fonts.bold, width - distance_w - 4),
        font=fonts.bold.font,
        fill=bright if live else dim,
    )
    if distance:
        draw.text(
            (width - distance_w, top), distance, font=fonts.bold.font, fill=bright
        )
    y = top + fonts.bold.height + 2
    draw.text((0, y), _fit(detail, fonts.small, width), font=fonts.small.font, fill=dim)
    y += fonts.small.height + 3

    # Progress bar of a slew: a faint track, the done part bright.
    progress = _progress(state, status)
    state.last_phase = status.phase if status is not None else ""
    if progress is not None:
        draw.rectangle((0, y, width - 1, y + 1), fill=faint)
        done = int((width - 1) * max(0.0, min(1.0, progress)))
        if done > 0:
            draw.rectangle((0, y, done, y + 1), fill=bright)
    y += 4

    # Keypad map: 3 columns, 3 rows of keys and a full-width STOP row.
    gap = 2
    rows = 4
    cell_h = (height - y - gap * (rows - 1)) // rows
    cell_w = (width - gap * 2) // 3
    labels = key_labels(connected, letters)
    numbers = state.showing_numbers(now)
    # The next step is the highlighted key: GOTO, or Connect without a mount.
    primary_key = 5 if connected else 1

    def cell_box(row: int, col: int, span: int = 1) -> tuple[int, int, int, int]:
        x0 = col * (cell_w + gap)
        y0 = y + row * (cell_h + gap)
        x1 = x0 + cell_w * span + gap * (span - 1) - 1
        y1 = y0 + cell_h - 1
        # The last column and row take the pixels the division left over.
        if col + span == 3:
            x1 = width - 1
        if row == rows - 1:
            y1 = height - 1
        return x0, y0, x1, y1

    def draw_cell(
        key: int, box, primary: bool = False, outline: Optional[tuple] = None
    ) -> None:
        icon, label = labels[key]
        flash = state.flashing(key, now)
        filled = primary or flash
        if filled:
            draw.rectangle(box, fill=bright if flash else mid)
        else:
            draw.rectangle(box, outline=outline or faint)
        usable = live and (connected or key not in _MOVE_KEYS)
        ink = colors.get(0) if filled else (bright if usable else dim)
        # Just after the page opens, the key number takes the icon's place.
        lead = str(key) if numbers else icon
        room = box[2] - box[0] - 2
        # Too wide: drop the icon, then use the small font.
        for text, font in (
            (f"{lead} {label}", fonts.base),
            (label, fonts.base),
            (label, fonts.small),
        ):
            if draw.textlength(text, font=font.font) <= room:
                break
        _centered(draw, box, text, font, ink)

    for key, (row, col) in KEY_CELLS.items():
        draw_cell(key, cell_box(row, col), primary=(key == primary_key))
    draw_cell(STOP_KEY, cell_box(3, 0, span=3), outline=dim)


def draw_connect_page(
    draw,
    display_class,
    fonts,
    colors,
    status: Optional[MountStatus],
    setup: MountSetup,
    state: MountPageState,
    now: Optional[float] = None,
) -> None:
    """The mount page without a connected mount: why, what is set up, and
    two actions: 1 Connect, 2 Settings."""
    now = time.time() if now is None else now
    width = display_class.resX
    height = display_class.resY
    top = display_class.titlebar_height + 2
    bright, mid, dim, faint = (
        colors.get(255),
        colors.get(160),
        colors.get(96),
        colors.get(40),
    )
    connecting = status is not None and status.phase == "MOUNT_INIT_TELESCOPE"
    answering = status is not None and not status.is_stale(now)

    # Title: what is wrong, or that it is working on it.
    if connecting:
        title = _("CONNECTING") + "." * (1 + int(now * 2) % 3)
    elif answering:
        title = _("NOT CONNECTED")
    else:
        title = _("NO STATUS")
    draw.text(
        (0, top), _fit(title, fonts.bold, width), font=fonts.bold.font, fill=bright
    )
    y = top + fonts.bold.height + 3

    # Why: the last fault, or the next step.
    if connecting:
        reason = _("Starting the driver and the mount")
    elif not answering:
        reason = _("Mount control does not answer")
    elif status is not None and status.error:
        reason = status.error
    elif not setup.model:
        reason = _("No mount selected")
    else:
        reason = _("Press 1 to connect")
    for line in _wrap(reason, fonts.base, width, 2):
        draw.text((0, y), line, font=fonts.base.font, fill=mid)
        y += fonts.base.height + 1
    y += 3

    # What is set up: the mount and the link.
    label_w = fonts.small.width * 6
    link = setup.link_text()
    if setup.connection == "wifi" and setup.address:
        # An address says WiFi already; drop the word if the line is full.
        if len(link) * fonts.small.width > width - label_w:
            link = setup.address
    for label, value in (
        (_("Mount"), setup.model or "-"),
        (_("Link"), link),
    ):
        draw.text((0, y), label, font=fonts.small.font, fill=dim)
        draw.text(
            (label_w, y),
            _fit(value, fonts.small, width - label_w),
            font=fonts.small.font,
            fill=mid,
        )
        y += fonts.small.height + 2

    # Two actions, full width, at the bottom.
    gap = 3
    row_h = min(max(fonts.bold.height + 6, 16), (height - y - gap) // 2)
    actions = (
        (CONNECT_KEY, ICON_INIT, _("Connect"), not connecting and bool(setup.model)),
        (SETTINGS_KEY, ICON_SETTINGS, _("Settings"), True),
    )
    box_y = height - 2 * row_h - gap
    for index, (key, icon, label, enabled) in enumerate(actions):
        box = (0, box_y, width - 1, box_y + row_h - 1)
        flash = state.flashing(key, now)
        primary = index == 0 and enabled
        if flash or primary:
            draw.rectangle(box, fill=bright if flash else mid)
            ink = colors.get(0)
        else:
            draw.rectangle(box, outline=dim if enabled else faint)
            ink = bright if enabled else dim
        draw.text(
            (4, box[1] + (row_h - fonts.bold.height) / 2),
            str(key),
            font=fonts.bold.font,
            fill=ink,
        )
        _centered(draw, box, f"{icon} {label}", fonts.bold, ink)
        box_y += row_h + gap
