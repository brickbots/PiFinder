"""Unit tests for PiFinder.recovery_hold: SQUARE held at power-on (ADR 0038).

A fake GPIO module models the keypad matrix: a closed switch pulls its
column LOW while its row is driven LOW.
"""

import pytest

from PiFinder import keypad, recovery_hold
from PiFinder.keyboard_interface import KeyboardInterface as K


class FakeGPIO:
    BCM = "BCM"
    IN = "IN"
    OUT = "OUT"
    LOW = 0
    HIGH = 1
    PUD_UP = "PUD_UP"

    def __init__(self, closed=(), fail_on_input=False):
        self.closed = set(closed)
        self.fail_on_input = fail_on_input
        self.modes = {}
        self.cleaned = None
        self.mode = None

    def setwarnings(self, _flag):
        pass

    def setmode(self, mode):
        self.mode = mode

    def setup(self, pins, mode, initial=None, pull_up_down=None):
        for pin in pins if isinstance(pins, list) else [pins]:
            self.modes[pin] = (mode, initial)

    def input(self, col_pin):
        if self.fail_on_input:
            raise RuntimeError("no GPIO")
        col = keypad.MATRIX_COLS.index(col_pin)
        for row, row_pin in enumerate(keypad.MATRIX_ROWS):
            driven = self.modes.get(row_pin) == (self.OUT, self.LOW)
            if driven and (row, col) in self.closed:
                return self.LOW
        return self.HIGH

    def cleanup(self, pins):
        self.cleaned = list(pins)


def _no_sleep(_seconds):
    pass


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(recovery_hold.time, "sleep", _no_sleep)


@pytest.mark.unit
def test_square_positions_are_both_square_switches():
    assert recovery_hold.SQUARE_POSITIONS == {(3, 3), (4, 4)}
    assert all(
        keypad.key_at(*pos) == K.SQUARE for pos in recovery_hold.SQUARE_POSITIONS
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "closed, held",
    [
        ({(3, 3)}, True),  # rev3 and rev4 calculator pad
        ({(4, 4)}, True),  # rev4 cluster centre
        ({(3, 3), (4, 4)}, True),
        (set(), False),
        ({(0, 0)}, False),
        ({(3, 3), (1, 3)}, False),  # SQUARE + PLUS is a chord
    ],
)
def test_is_recovery_hold(closed, held):
    assert recovery_hold.is_recovery_hold(closed) is held


@pytest.mark.unit
def test_square_held_needs_every_scan():
    scans = iter([{(3, 3)}, {(3, 3)}, set()])
    assert not recovery_hold.square_held(lambda: next(scans), scans=3, sleep=_no_sleep)


@pytest.mark.unit
def test_square_held_through_all_scans():
    calls = []

    def scan():
        calls.append(1)
        return {(3, 3)}

    assert recovery_hold.square_held(scan, scans=5, sleep=_no_sleep)
    assert len(calls) == 5


@pytest.mark.unit
def test_closed_positions_reads_the_matrix():
    gpio = FakeGPIO(closed={(3, 3), (0, 1)})
    assert recovery_hold.closed_positions(gpio) == {(3, 3), (0, 1)}
    # Every row goes back to an input after the scan.
    for pin in keypad.MATRIX_ROWS:
        assert gpio.modes[pin][0] == FakeGPIO.IN


@pytest.mark.unit
@pytest.mark.parametrize("square", [(3, 3), (4, 4)])
def test_detect_sees_a_held_square(square):
    gpio = FakeGPIO(closed={square})
    assert recovery_hold.detect(gpio, sleep=_no_sleep)
    assert gpio.mode == FakeGPIO.BCM
    assert sorted(gpio.cleaned) == sorted(keypad.MATRIX_ROWS + keypad.MATRIX_COLS)


@pytest.mark.unit
def test_detect_ignores_a_column_that_reads_low():
    """A matrix fault reads as many closed keys and is not a hold."""
    stuck = {(row, 3) for row in range(len(keypad.MATRIX_ROWS))}
    assert not recovery_hold.detect(FakeGPIO(closed=stuck), sleep=_no_sleep)


@pytest.mark.unit
def test_detect_releases_the_pins_after_a_fault():
    gpio = FakeGPIO(closed={(3, 3)}, fail_on_input=True)
    with pytest.raises(RuntimeError):
        recovery_hold.detect(gpio, sleep=_no_sleep)
    assert gpio.cleaned is not None


@pytest.mark.unit
def test_run_writes_the_flag_and_shows_the_message(tmp_path, monkeypatch):
    flag = tmp_path / "recovery-mode"
    shown = []
    monkeypatch.setattr(recovery_hold, "show_splash", lambda: shown.append(1))
    assert recovery_hold.run(FakeGPIO(closed={(3, 3)}), flag)
    assert flag.exists()
    assert shown == [1]


@pytest.mark.unit
def test_run_without_hold_writes_nothing(tmp_path, monkeypatch):
    flag = tmp_path / "recovery-mode"
    monkeypatch.setattr(recovery_hold, "show_splash", lambda: None)
    assert not recovery_hold.run(FakeGPIO(), flag)
    assert not flag.exists()


@pytest.mark.unit
def test_run_survives_a_gpio_fault(tmp_path):
    flag = tmp_path / "recovery-mode"
    assert not recovery_hold.run(FakeGPIO(closed={(3, 3)}, fail_on_input=True), flag)
    assert not flag.exists()


@pytest.mark.unit
def test_run_without_gpio_is_a_normal_boot(tmp_path):
    flag = tmp_path / "recovery-mode"
    assert not recovery_hold.run(None, flag)
    assert not flag.exists()


@pytest.mark.unit
def test_run_survives_a_flag_it_cannot_write(tmp_path, monkeypatch):
    flag = tmp_path / "missing-dir" / "recovery-mode"
    shown = []
    monkeypatch.setattr(recovery_hold, "show_splash", lambda: shown.append(1))
    assert not recovery_hold.run(FakeGPIO(closed={(3, 3)}), flag)
    assert shown == []


@pytest.mark.unit
def test_main_always_exits_zero():
    assert recovery_hold.main(FakeGPIO(fail_on_input=True)) == 0


@pytest.mark.unit
def test_show_splash_survives_a_missing_binary(monkeypatch):
    def missing(*_args, **_kwargs):
        raise FileNotFoundError("boot-splash")

    monkeypatch.setattr(recovery_hold.subprocess, "run", missing)
    recovery_hold.show_splash()
