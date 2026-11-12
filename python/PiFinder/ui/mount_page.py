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

from PiFinder.types.mount import MountStatus, format_step

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

# Phases that move the mount: the distance bar shows the progress.
_MOVING_PHASES = ("MOUNT_TARGET_ACQUISITION_MOVE", "MOUNT_TARGET_ACQUISITION_REFINE")


def key_labels() -> dict[int, tuple[str, str]]:
    """Key -> (icon, label). The labels are short: a cell is about 40 px."""
    return {
        7: (ICON_SYNC, _("Sync")),
        8: (ICON_UP, _("N")),
        9: (ICON_PLUS, _("Step")),
        4: (ICON_LEFT, _("W")),
        5: (ICON_GOTO, _("GOTO")),
        6: (ICON_RIGHT, _("E")),
        1: (ICON_INIT, _("Init")),
        2: (ICON_DOWN, _("S")),
        3: (ICON_MINUS, _("Step")),
        STOP_KEY: (ICON_STOP, _("STOP")),
    }


@dataclass
class MountPageState:
    """What the page remembers between frames."""

    pressed_key: Optional[int] = None
    pressed_at: float = 0.0
    # The largest distance of the current slew, for the progress bar.
    slew_start_distance: Optional[float] = None
    last_phase: str = field(default="")

    def press(self, key: int, now: Optional[float] = None) -> None:
        self.pressed_key = key
        self.pressed_at = time.time() if now is None else now

    def flashing(self, key: int, now: float) -> bool:
        return self.pressed_key == key and now - self.pressed_at < PRESS_FLASH_S


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
) -> tuple[str, str, str, bool]:
    """(phase, distance, detail, live) for the status band."""
    if status is None or status.is_stale(now):
        return _("NO MOUNT"), "", _("No status from the mount"), False
    distance = ""
    if status.distance_deg is not None and status.phase in (
        *_MOVING_PHASES,
        "MOUNT_DRIFT_COMPENSATION",
    ):
        distance = format_step(status.distance_deg)
    detail = _("step") + " " + format_step(status.step_deg)
    return status.text.upper(), distance, detail, True


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
    phase, distance, detail, live = _status_texts(status, now)
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
    labels = key_labels()

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
        ink = colors.get(0) if filled else (bright if live else dim)
        text = f"{icon} {label}" if label else icon
        _centered(draw, box, text, fonts.base, ink)

    for key, (row, col) in KEY_CELLS.items():
        draw_cell(key, cell_box(row, col), primary=(key == 5))
    draw_cell(STOP_KEY, cell_box(3, 0, span=3), outline=dim)
