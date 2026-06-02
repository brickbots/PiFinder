"""
Player smoke test: ``play_earcon`` drives the buzzer seam with the expected
``(freq, duty)`` sequence and silences afterwards.

A fake driver records the calls and ``time.sleep`` is monkeypatched to a
no-op, so there is no hardware and no wall-clock delay.
"""

import pytest

from PiFinder import sound
from PiFinder.sound import MAX_DUTY, CATALOG, note_duty, play_earcon, play_tone
from PiFinder.types.sound import Earcon


class FakeDriver:
    """Records tone()/silence()/stop() calls instead of touching PWM."""

    def __init__(self):
        self.calls = []

    def tone(self, freq_hz, duty):
        self.calls.append(("tone", freq_hz, duty))

    def silence(self):
        self.calls.append(("silence",))

    def stop(self):
        self.calls.append(("stop",))


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(sound.time, "sleep", lambda _s: None)


@pytest.mark.unit
def test_play_earcon_drives_expected_sequence(no_sleep):
    """A KEYPRESS at level 5 yields its note's (freq, duty) then silence."""
    driver = FakeDriver()
    play_earcon(driver, Earcon.KEYPRESS, "5")

    expected = [
        ("tone", n.frequency_hz, note_duty("5", n.volume))
        for n in CATALOG[Earcon.KEYPRESS].notes
    ]
    expected.append(("silence",))
    assert driver.calls == expected


@pytest.mark.unit
def test_play_earcon_multi_note_in_order(no_sleep):
    """STARTUP's two notes are emitted in order, then a single silence."""
    driver = FakeDriver()
    play_earcon(driver, Earcon.STARTUP, "3")

    tones = [c for c in driver.calls if c[0] == "tone"]
    assert [c[1] for c in tones] == [
        n.frequency_hz for n in CATALOG[Earcon.STARTUP].notes
    ]
    assert driver.calls[-1] == ("silence",)


@pytest.mark.unit
def test_play_earcon_off_is_silent_but_keeps_rhythm(no_sleep):
    """At ``Off`` every tone() is called with duty 0 (silent) — the rhythm is
    still walked, so a muted earcon costs its duration but makes no sound."""
    driver = FakeDriver()
    play_earcon(driver, Earcon.STARTUP, "Off")

    tones = [c for c in driver.calls if c[0] == "tone"]
    assert tones  # rhythm still emitted
    assert all(duty == 0.0 for _tag, _freq, duty in tones)


@pytest.mark.unit
def test_play_tone_passes_duty_through_unchanged(no_sleep):
    """play_tone uses an absolute duty (no master-volume mapping) then
    silences."""
    driver = FakeDriver()
    play_tone(driver, 4000, 200, 25.0)
    assert driver.calls == [("tone", 4000, 25.0), ("silence",)]


@pytest.mark.unit
def test_play_tone_clamps_duty_to_max(no_sleep):
    """A duty above MAX_DUTY is clamped; a negative duty floors at 0."""
    driver = FakeDriver()
    play_tone(driver, 4000, 50, 80.0)
    play_tone(driver, 4000, 50, -5.0)
    tone_calls = [c for c in driver.calls if c[0] == "tone"]
    assert tone_calls[0] == ("tone", 4000, MAX_DUTY)
    assert tone_calls[1] == ("tone", 4000, 0.0)
