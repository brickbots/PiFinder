"""
Dataclasses for the Sound (Audio Feedback) context.

These types implement the canonical Sound vocabulary (see
``docs/ax/sound/CONTEXT.md`` and
``docs/adr/0008-sound-best-effort-delivery.md``).

* An **earcon** is a named, recognizable short cue tied to an event
  (``startup``, ``keypress``…). Producers request one **by name**
  (:class:`Earcon`) — they never put note data on the wire.
* A **note** is the atomic unit an earcon is built from: a frequency
  (pitch), a duration, and an **intent volume** (``0.0``–``1.0``,
  perceptual — *not* a duty cycle; the messy duty mapping lives in one
  place in :mod:`PiFinder.sound`). ``volume=0`` is a rest.
* An :class:`EarconDef` is the catalog entry: the ordered notes plus the
  **important** flag (important earcons are exempt from staleness and win
  the drain — see :class:`PlayEarcon`).

This module is **pure and import-safe everywhere**: no hardware imports,
so producers on any board (or a dev machine) can construct an
:class:`Earcon` name without touching the buzzer.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class Earcon(Enum):
    """The named cues a producer can request. The *name* is what travels
    on ``sound_queue``; the note data lives in the Sound-context catalog.
    """

    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    KEYPRESS = "keypress"
    VOLUME_SAMPLE = "volume_sample"
    LOW_BATTERY = "low_battery"  # advisory 10%/5% warnings (ADR 0021)
    # Defined-but-unwired in v1: catalog entries exist (so the data model is
    # complete) but no producer requests them yet.
    ERROR = "error"
    SOLVE_LOCK = "solve_lock"


@dataclass(frozen=True)
class Note:
    """One note of an earcon: a pitch, a hold time, and an intent volume.

    ``volume`` is a per-note authored loudness *intention* (``0.0``–``1.0``,
    perceptual), not a duty cycle. ``volume=0`` is a rest (silence held for
    ``duration_ms``).
    """

    frequency_hz: int  # pitch
    duration_ms: int  # how long to hold it
    volume: float = 1.0  # intent volume 0.0-1.0; volume=0 is a rest


@dataclass(frozen=True)
class EarconDef:
    """A catalog entry: the ordered notes for an earcon plus whether it is
    **important** (exempt from staleness; wins the drain)."""

    notes: Tuple[Note, ...]
    important: bool = False


# --- the two message types carried on sound_queue ---
@dataclass(frozen=True)
class PlayEarcon:
    """Request to play an earcon. ``requested_at`` is a ``time.monotonic()``
    stamp taken at the producer; the player uses it to drop stale transient
    requests (see ADR 0008). Monotonic (not wall-clock) so a GPS clock step
    can't make queued requests look ancient or future-dated."""

    earcon: Earcon
    requested_at: float


@dataclass(frozen=True)
class SetVolume:
    """Push a new master-volume level to the player. ``level`` is one of
    ``"Off"``, ``"1"`` … ``"5"`` (the ``Config`` ``sound_volume`` values)."""

    level: str
