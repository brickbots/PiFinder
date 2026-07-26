"""
Unit tests for ``PiFinder.keypad`` — the keypad matrix wiring shared by the
keyboard scanner and bring-up (see ``docs/ax/bringup/CONTEXT.md``).

Two things are worth guarding here:

* the **population maps**, which say how many switches each board revision
  actually carries. They set bring-up's PASS gate, so an error in either
  direction is expensive: too many expected and PASS never arrives, too few
  and a dead switch passes silently.
* the **extraction itself** — that ``KeyboardPi`` really reads its rows,
  columns and keymaps from this module rather than keeping a private copy that
  can drift.

``keyboard_pi`` imports ``libinput`` and ``RPi.GPIO`` at module scope and can
only be imported on a Pi, so the extraction test stubs both.
"""

import sys
import types

import pytest

from PiFinder import keypad
from PiFinder.keyboard_interface import KeyboardInterface as K


@pytest.mark.unit
def test_population_map_sizes():
    """rev3 carries 17 switches, rev4 carries 18."""
    assert len(keypad.REV3_POPULATED) == 17
    assert len(keypad.REV4_POPULATED) == 18


@pytest.mark.unit
def test_rev3_is_the_first_four_columns():
    """rev3 populates cols 0-3 of every row, including the bottom
    directional row, and nothing in col 4."""
    assert all(col < 4 for _, col in keypad.REV3_POPULATED)
    assert {(4, col) for col in range(4)} <= keypad.REV3_POPULATED


@pytest.mark.unit
def test_rev4_populates_all_of_column_four_and_no_bottom_row():
    """rev4 moved the directional cluster into col 4 -- all five rows of it,
    including the centre SQUARE at (4,4) -- and left the rest of the bottom
    row unpopulated."""
    assert {(row, 4) for row in range(5)} <= keypad.REV4_POPULATED
    assert not {(4, col) for col in range(4)} & keypad.REV4_POPULATED


@pytest.mark.unit
def test_rev4_has_two_square_switches():
    """The calculator pad's SQUARE at (3,3) and the cluster's centre SQUARE
    at (4,4) are distinct switches sending the same key."""
    squares = {pos for pos in keypad.REV4_POPULATED if keypad.key_at(*pos) == K.SQUARE}
    assert squares == {(3, 3), (4, 4)}


@pytest.mark.unit
@pytest.mark.parametrize("revision", ["rev3", "rev4"])
def test_every_populated_position_has_a_real_key(revision):
    """A populated position must map to a non-NA keymap entry -- a switch the
    builder is asked to close that the running UI would ignore.

    Honest about its own strength: the maps are *derived* from the keymap
    through the same NA filter, so this restates the derivation rather than
    checking it independently. What makes the pair meaningful is
    ``test_population_map_sizes``, which states 17 and 18 independently of how
    they are computed -- change either table and one of the two fails.

    The reason the maps are derived rather than hand-listed is that the likelier
    error is a keymap edit silently changing which positions count as switches;
    deriving makes that impossible to do quietly. The cost is that a revision
    fitting a switch the UI ignores could not be expressed without also editing
    KEYMAP -- no such revision exists, and if one appears these become explicit
    position sets.
    """
    for row, col in keypad.POPULATION_MAPS[revision]:
        assert keypad.key_at(row, col) != K.NA, f"({row},{col}) is NA in the keymap"


@pytest.mark.unit
def test_keymap_index_is_row_major():
    assert keypad.keymap_index(0, 0) == 0
    assert keypad.keymap_index(1, 0) == len(keypad.MATRIX_COLS)
    assert keypad.keymap_index(4, 4) == len(keypad.KEYMAP) - 1


@pytest.mark.unit
def test_tables_are_all_one_entry_per_matrix_position():
    expected = len(keypad.MATRIX_ROWS) * len(keypad.MATRIX_COLS)
    assert len(keypad.KEYMAP) == expected
    assert len(keypad.ALT_KEYMAP) == expected
    assert len(keypad.LONG_KEYMAP) == expected


@pytest.fixture
def keyboard_pi_module(monkeypatch):
    """Import ``PiFinder.keyboard_pi`` with its Pi-only imports stubbed.

    ``libinput`` and ``RPi.GPIO`` are absent on a dev box; the scanner only
    touches them at construction (``LibInput``/``assign_seat``) and inside
    ``run_keyboard``, which this never calls.
    """
    libinput_stub = types.ModuleType("libinput")

    class _LibInput:
        def __init__(self, context_type=None):
            pass

        def assign_seat(self, seat):
            pass

    libinput_stub.LibInput = _LibInput
    libinput_stub.ContextType = types.SimpleNamespace(UDEV=object())
    libinput_stub.KeyboardEvent = object
    libinput_stub.constant = types.SimpleNamespace(
        KeyState=types.SimpleNamespace(RELEASED=object())
    )

    rpi_stub = types.ModuleType("RPi")
    gpio_stub = types.ModuleType("RPi.GPIO")
    rpi_stub.GPIO = gpio_stub

    monkeypatch.setitem(sys.modules, "libinput", libinput_stub)
    monkeypatch.setitem(sys.modules, "RPi", rpi_stub)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", gpio_stub)
    monkeypatch.delitem(sys.modules, "PiFinder.keyboard_pi", raising=False)

    import PiFinder.keyboard_pi as keyboard_pi

    yield keyboard_pi

    # Leave no half-stubbed module behind for later tests to import.
    sys.modules.pop("PiFinder.keyboard_pi", None)


@pytest.mark.unit
def test_keyboard_pi_sources_its_wiring_from_keypad(keyboard_pi_module):
    """Guards the extraction: the scanner must not keep a private copy."""
    kb = keyboard_pi_module.KeyboardPi(q=None)

    assert kb.rows is keypad.MATRIX_ROWS
    assert kb.cols is keypad.MATRIX_COLS
    assert kb.power_gpio == keypad.POWER_GPIO
    assert kb.keymap is keypad.KEYMAP
    assert kb.alt_keymap is keypad.ALT_KEYMAP
    assert kb.long_keymap is keypad.LONG_KEYMAP


@pytest.mark.unit
def test_keyboard_pi_derived_keycodes_survive_the_extraction(keyboard_pi_module):
    """``square_keycodes`` / ``repeat_keycodes`` are comprehensions over the
    keymap; they must still resolve to the same keymap indices."""
    kb = keyboard_pi_module.KeyboardPi(q=None)

    assert kb.square_keycodes == {
        keypad.keymap_index(3, 3),
        keypad.keymap_index(4, 4),
    }
    assert kb.repeat_keycodes == {
        keypad.keymap_index(0, 4),  # UP, rev4 cluster
        keypad.keymap_index(2, 4),  # DOWN, rev4 cluster
        keypad.keymap_index(4, 1),  # UP, rev3 bottom row
        keypad.keymap_index(4, 2),  # DOWN, rev3 bottom row
    }
