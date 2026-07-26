#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Keypad matrix wiring: the physical truth about the keypad, shared by the
keyboard scanner (``keyboard_pi``) and bring-up (``PiFinder.bringup``).

Pure data, **import-safe everywhere** — no ``RPi.GPIO``, no ``libinput``. That
is the whole point of the module: ``keyboard_pi`` imports both of those at
module scope and therefore cannot be imported on a dev box or in a unit test,
so the tables cannot live there if anything else is to read them.

Two different tables describe the keypad and they must not be confused (see
``docs/ax/bringup/CONTEXT.md``):

* the **keymap** maps a matrix position to the logical **key** the UI receives
  (``UP``, ``ALT_PLUS``, ...) — several positions can send the same key;
* the **population map** says which matrix positions actually carry a
  **switch** on a given board revision — the physical joints bring-up checks.

The matrix is scanned identically on every revision; revisions differ only in
which positions are populated.
"""

from typing import FrozenSet, List, Tuple

from PiFinder.keyboard_interface import KeyboardInterface as K

# GPIO pin numbers (BCM) for the rows and columns of the keypad matrix.
# Rows are driven LOW one at a time as outputs; columns are read with
# pull-ups, so a closed switch reads LOW.
MATRIX_COLS: List[int] = [16, 23, 26, 27, 21]
MATRIX_ROWS: List[int] = [19, 17, 18, 22, 20]

# The power switch is wired to its own GPIO, not into the matrix, and has no
# matrix position. It has its own pull-up in hardware and goes LOW when closed.
POWER_GPIO: int = 15

# fmt: off
KEYMAP: List[int] = [
    7 , 8 , 9 , K.NA, K.UP,
    4 , 5 , 6 , K.PLUS, K.LEFT,
    1 , 2 , 3 , K.MINUS, K.DOWN,
    K.NA, 0 , K.NA, K.SQUARE, K.RIGHT,
    K.LEFT, K.UP , K.DOWN , K.RIGHT, K.SQUARE,
]
# If SQUARE is pressed together with key, ALT_<key> is sent
ALT_KEYMAP: List[int] = [
    K.NA, K.NA, K.NA, K.NA, K.ALT_UP,
    K.NA, K.NA, K.NA, K.ALT_PLUS, K.ALT_LEFT,
    K.NA, K.NA, K.NA, K.ALT_MINUS, K.ALT_DOWN,
    K.NA, K.ALT_0, K.NA, K.NA, K.ALT_RIGHT,
    K.ALT_LEFT, K.ALT_UP, K.ALT_DOWN, K.ALT_RIGHT, K.NA,
]
LONG_KEYMAP: List[int] = [
    K.NA, K.NA, K.NA, K.NA, K.LNG_UP,
    K.NA, K.NA, K.NA, K.NA, K.LNG_LEFT,
    K.NA, K.NA, K.NA, K.NA, K.LNG_DOWN,
    K.NA, K.NA, K.NA, K.LNG_SQUARE, K.LNG_RIGHT,
    K.LNG_LEFT, K.LNG_UP, K.LNG_DOWN, K.LNG_RIGHT, K.LNG_SQUARE,
]
# fmt: on


def keymap_index(row: int, col: int) -> int:
    """Matrix position ``(row, col)`` -> index into :data:`KEYMAP` and friends.

    Named for what it returns. A **matrix position** is the ``(row, col)``
    pair itself (see the glossary, which lists "index" as a word to avoid for
    it); this is the flat offset the tables happen to be stored at.
    """
    return row * len(MATRIX_COLS) + col


def key_at(row: int, col: int) -> int:
    """The logical key a switch at this matrix position sends."""
    return KEYMAP[keymap_index(row, col)]


def _populated(rows: range, cols: range) -> FrozenSet[Tuple[int, int]]:
    """Positions in this row/column block that carry a switch.

    A position is populated when the keymap gives it a real key; ``NA`` marks
    a hole in the block (the calculator pad is not a full rectangle).
    """
    return frozenset(
        (row, col) for row in rows for col in cols if key_at(row, col) != K.NA
    )


# --- Population maps: which positions carry a switch on each revision -------
#
#        col0  col1  col2  col3    col4
# row0    7     8     9    (na)    UP     |
# row1    4     5     6    PLUS    LEFT   | col4 = the directional cluster
# row2    1     2     3    MINUS   DOWN   | added for rev4, with a centre
# row3   (na)   0    (na)  SQUARE  RIGHT  | SQUARE of its own
# row4    LEFT  UP    DOWN  RIGHT  SQUARE |
#         |__ rev3 directional row __|
#            (unpopulated on rev4)
#
# rev3: cols 0-3 of every row -- the calculator pad plus a directional row
# along the bottom. 17 switches (three NA holes).
REV3_POPULATED: FrozenSet[Tuple[int, int]] = _populated(range(5), range(4))

# rev4: the directional cluster moved off the bottom row into column 4 and
# gained a centre SQUARE, so ALL FIVE rows of col 4 are populated while only
# rows 0-3 of cols 0-3 are. 13 + 5 = 18 switches, and two positions send
# SQUARE -- (3,3) on the calculator pad and (4,4) in the cluster.
# Both halves go through the same NA filter: col 4 has no holes today, but
# deriving one half differently from the other is how the two tables start to
# disagree.
REV4_POPULATED: FrozenSet[Tuple[int, int]] = _populated(
    range(4), range(4)
) | _populated(range(5), range(4, 5))

POPULATION_MAPS = {
    "rev3": REV3_POPULATED,
    "rev4": REV4_POPULATED,
}
