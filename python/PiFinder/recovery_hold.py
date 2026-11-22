"""The recovery hold: SQUARE held at power-on starts recovery mode (ADR 0038).

pifinder-recovery-hold.service runs this once per boot, as root, before
pifinder.service. It scans the keypad matrix a few times. When SQUARE is
held and no other key is closed in each scan, it writes the recovery flag
(PiFinder.generations.RECOVERY_FLAG) and shows a message on the screen.
pifinder.service then starts PiFinder.recovery in place of PiFinder.main.

The scan uses the same pins and the same electrical scheme as keyboard_pi,
which is the same on rev3 and rev4: the revisions differ only in which
matrix positions carry a switch. Rev4 has a second SQUARE at (4,4). On rev3
that position has no switch and always reads open.

A failure here must never stop a normal boot. Every error is logged, the
flag is not written, and the exit status is 0.
"""

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, FrozenSet, Optional, Set, Tuple

from PiFinder import keypad
from PiFinder.generations import RECOVERY_FLAG
from PiFinder.keyboard_interface import KeyboardInterface

try:
    import RPi.GPIO as GPIO
except (ImportError, RuntimeError):
    # Not a Raspberry Pi (a development machine or a unit test).
    GPIO = None

logger = logging.getLogger("RecoveryHold")

Position = Tuple[int, int]

# SQUARE must be held in every scan: 10 scans 50 ms apart, about 0.5 s.
SCANS = 10
SCAN_INTERVAL = 0.05
# Time for the column pull-ups to settle after the pins are set up.
SETTLE_TIME = 0.01

SQUARE_POSITIONS: FrozenSet[Position] = frozenset(
    (row, col)
    for row in range(len(keypad.MATRIX_ROWS))
    for col in range(len(keypad.MATRIX_COLS))
    if keypad.key_at(row, col) == KeyboardInterface.SQUARE
)

SPLASH_LINES = ("RECOVERY", "MODE", "RELEASE SQUARE")


def is_recovery_hold(closed: Set[Position]) -> bool:
    """True when a SQUARE switch is closed and no other switch is.

    A second closed switch means a different chord or a matrix fault (for
    example a column that reads LOW at all times). Neither starts recovery.
    """
    return bool(closed & SQUARE_POSITIONS) and not (closed - SQUARE_POSITIONS)


def square_held(
    scan: Callable[[], Set[Position]],
    scans: int = SCANS,
    interval: float = SCAN_INTERVAL,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """True when every one of `scans` matrix scans is a recovery hold."""
    for index in range(scans):
        if index:
            sleep(interval)
        if not is_recovery_hold(scan()):
            return False
    return True


def closed_positions(gpio) -> Set[Position]:
    """One scan of the matrix: the positions whose switch is closed.

    Each row in turn is driven LOW. A closed switch pulls its column LOW.
    """
    closed = set()
    for row, row_pin in enumerate(keypad.MATRIX_ROWS):
        gpio.setup(row_pin, gpio.OUT, initial=gpio.LOW)
        try:
            for col, col_pin in enumerate(keypad.MATRIX_COLS):
                if gpio.input(col_pin) == gpio.LOW:
                    closed.add((row, col))
        finally:
            gpio.setup(row_pin, gpio.IN)
    return closed


def detect(gpio, sleep: Callable[[float], None] = time.sleep) -> bool:
    """Set up the matrix pins, look for the hold, and release the pins."""
    pins = keypad.MATRIX_ROWS + keypad.MATRIX_COLS
    gpio.setwarnings(False)
    gpio.setmode(gpio.BCM)
    try:
        gpio.setup(keypad.MATRIX_ROWS, gpio.IN)
        gpio.setup(keypad.MATRIX_COLS, gpio.IN, pull_up_down=gpio.PUD_UP)
        sleep(SETTLE_TIME)
        return square_held(lambda: closed_positions(gpio), sleep=sleep)
    finally:
        gpio.cleanup(pins)


def enter_recovery_mode(flag: Path = RECOVERY_FLAG) -> bool:
    """Write the recovery flag. Returns False when the write fails."""
    try:
        flag.write_text("square held at power-on\n")
    except OSError as exc:
        logger.error("Cannot write %s: %s", flag, exc)
        return False
    return True


def show_splash() -> None:
    """Tell the user that recovery mode starts. Best effort."""
    try:
        subprocess.run(
            ["boot-splash", "--message", *SPLASH_LINES],
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Cannot show the recovery message: %s", exc)


def run(gpio, flag: Path = RECOVERY_FLAG) -> bool:
    """Detect the hold and enter recovery mode. Never raises.

    Returns True when recovery mode starts.
    """
    if gpio is None:
        logger.info("No GPIO on this machine; normal boot")
        return False
    try:
        held = detect(gpio)
    except Exception:  # noqa: BLE001 - a fault here must not stop the boot
        logger.exception("Keypad scan failed; normal boot")
        return False
    if not held:
        logger.info("SQUARE is not held; normal boot")
        return False
    logger.warning("SQUARE is held at power-on; recovery mode")
    if not enter_recovery_mode(flag):
        return False
    show_splash()
    return True


def main(gpio: Optional[object] = GPIO) -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    run(gpio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
