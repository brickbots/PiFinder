#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Audio-feedback subsystem for the rev4 PiFinder's passive piezo buzzer
(hardware **PWM channel 0, GPIO12**, resonant ~4 kHz). Named events become
short **earcons** played on the buzzer.

This module holds four things:

* the **catalog** — the note data for each :class:`~PiFinder.types.sound.Earcon`;
* **pure logic** — :func:`note_duty`, :func:`total_duration_ms`,
  :func:`select_winner` (no hardware, no ``sleep`` — the unit-test targets,
  same discipline as ``battery_bq25895.decode_registers``);
* the :class:`BuzzerPWM` **seam** — a thin wrapper over ``rpi_hardware_pwm``
  channel 0, constructed only in the sound process on real hardware;
* the :func:`request` producer helper and the :func:`sound_monitor` process
  entry, which mirrors ``battery_monitor``.

Design background:

* ``docs/ax/sound/CONTEXT.md`` — glossary (earcon / note / intent volume /
  master volume / important-vs-transient / stale-max-age / resonance).
* ``docs/adr/0008-sound-best-effort-delivery.md`` — why delivery is
  best-effort, monotonic-stamped, latest-wins; the shutdown bounded wait.

The buzzer is a *passive* piezo: the PWM square wave **is** the tone, so
frequency = pitch and duty cycle = amplitude. Because of the ~4 kHz
resonance, loudness and pitch are coupled — earcons are designed near
resonance and convey identity by pitch contour / rhythm, never melody. We
only ever emit **0-50 %** duty (50 % is loudest; above it loudness falls off
and is never used).

Dev / rev3 boards have no buzzer: no process is spawned, ``sound_queue`` is
``None``, and :func:`request` no-ops after a debug log. There is deliberately
**no fake-playback path** — duty-as-volume on a 4 kHz piezo does not
translate to a PC speaker and would mislead earcon tuning.
"""

import argparse
import logging
import queue
import signal
import time
from typing import Dict, List, Optional, Tuple

from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.types.sound import Earcon, EarconDef, Note, PlayEarcon, SetVolume

logger = logging.getLogger("Sound")

PWM_CHANNEL = 0
PWM_HZ_DEFAULT = 4000  # ch0 base frequency; change_frequency() per note
DEFAULT_MAX_AGE_MS = 200  # transient staleness window
MAX_DUTY = 50.0  # never emit above this (the buzzer's loudest)

# Hand-tuned on hardware: peak duty (%) for a full-intent note at each master
# level. The non-linearity of perceived loudness vs level is absorbed here, so
# the rest of the code can treat intent volume as a clean multiplier. These are
# *starting* values — finalize them by ear on a real buzzer.
MASTER_DUTY: Dict[str, float] = {
    "Off": 0.0,
    "1": 6.0,
    "2": 12.0,
    "3": 22.0,
    "4": 35.0,
    "5": 50.0,
}

# The earcon catalog. Frequencies sit near the ~4 kHz resonant peak; identity
# is carried by pitch contour and rhythm. STARTUP/SHUTDOWN are important (never
# dropped); KEYPRESS is transient (dropped if it arrives stale). These note
# values are starting guesses — tune by ear on hardware.
CATALOG: Dict[Earcon, EarconDef] = {
    Earcon.STARTUP: EarconDef(
        important=True,
        # Rising "wake" cue, tuned by ear: G5-A5-C6-G6 (do-re-fa-do' in G major),
        # a gentle pentatonic-flavored climb that resolves up an octave to the
        # held tonic. The notes sit below the ~4 kHz resonance, so loudness rises
        # naturally toward the final note. ~12 ms rests articulate the run, and
        # the note lengths are deliberately de-quantized (not all equal) to give
        # the cue a looser, more natural feel rather than a metronomic one.
        notes=(
            Note(784, 101, 1.0),  # G5
            Note(0, 12),
            Note(880, 78, 1.0),  # A5
            Note(0, 12),
            Note(1047, 99, 1.0),  # C6
            Note(0, 12),
            Note(1568, 218, 1.0),  # G6 — held tonic
        ),
    ),
    Earcon.SHUTDOWN: EarconDef(
        important=True,
        # Falling "sleep" cue and bookend to STARTUP: G6-C6-G5 (do'-fa-do in G),
        # the startup's octave climb mirrored back down to the held low tonic.
        # ~12 ms rests articulate the descent; the note lengths carry the same
        # de-quantized (jittered) timing as STARTUP for a looser, natural feel.
        notes=(
            Note(1568, 132, 1.0),  # G6
            Note(0, 12),
            Note(1047, 107, 1.0),  # C6
            Note(0, 12),
            Note(784, 292, 1.0),  # G5 — held low tonic
        ),
    ),
    Earcon.KEYPRESS: EarconDef(notes=(Note(480, 10, 0.2),)),
    Earcon.VOLUME_SAMPLE: EarconDef(notes=(Note(4000, 120, 1.0),)),
    # Defined-but-unwired in v1 (no producer requests these yet). They have
    # catalog entries so the data model is complete and they are tunable now.
    Earcon.ERROR: EarconDef(
        important=True,
        notes=(Note(2000, 120, 1.0), Note(0, 40), Note(2000, 120, 1.0)),
    ),
    Earcon.LOW_BATTERY: EarconDef(
        important=True,
        notes=(Note(4000, 100, 1.0), Note(0, 60), Note(3000, 200, 0.9)),
    ),
    Earcon.SOLVE_LOCK: EarconDef(notes=(Note(3500, 40, 0.7), Note(4500, 60, 0.9))),
}


# --- Pure functions (no hardware, no sleep — the unit-test targets) ---


def note_duty(level: str, note_volume: float) -> float:
    """Emitted duty cycle (%) for one note at a master ``level``.

    ``duty = MASTER_DUTY[level] * note_volume``, with the note volume clamped
    to ``[0, 1]`` and the result clamped to ``[0, MAX_DUTY]``. An unknown level
    maps to ``0`` (silent), so ``"Off"`` and any bad value mute. PURE.
    """
    vol = max(0.0, min(1.0, note_volume))
    return min(MAX_DUTY, MASTER_DUTY.get(level, 0.0) * vol)


def total_duration_ms(earcon: Earcon) -> int:
    """Sum of an earcon's note durations (ms). Used by the shutdown bounded
    wait to know how long the cue takes. PURE."""
    return sum(n.duration_ms for n in CATALOG[earcon].notes)


def select_winner(
    pending: List[Tuple[Earcon, float]],
    now: float,
    max_age_ms: int = DEFAULT_MAX_AGE_MS,
) -> Optional[Earcon]:
    """Drain policy: pick the single earcon to play from a batch. PURE.

    ``pending`` is ``(earcon, requested_at_monotonic)`` pairs in arrival order;
    ``now`` is a ``time.monotonic()`` reading.

    * **Important** earcons never expire and win the drain (a flood of
      transients can't bury one).
    * **Transient** earcons older than ``max_age_ms`` are stale and dropped
      (a beep that lands after the user saw the result is worse than silence).
    * Among survivors: the newest important if any, else the newest transient.

    Returns ``None`` if nothing survives.

    v1 returns a **single** winner per drain. The player plays it to
    completion (non-preemptive) then drains and selects again. A
    drained-but-not-chosen important earcon is **dropped**, not replayed on the
    next pass: importance protects an earcon from being buried *within* a
    drain, not across drains. (Earcons are <1 s, so this is rarely observable;
    revisit if a queued-behind-another important cue must still play.)
    """
    important: List[Tuple[Earcon, float]] = []
    transient: List[Tuple[Earcon, float]] = []
    for earcon, ts in pending:
        if CATALOG[earcon].important:
            important.append((earcon, ts))
        elif (now - ts) * 1000.0 <= max_age_ms:
            transient.append((earcon, ts))
    pool = important or transient
    if not pool:
        return None
    return max(pool, key=lambda et: et[1])[0]


# --- Hardware seam (constructed only in the sound process on real hardware) ---


class BuzzerPWM:
    """Thin wrapper over ``rpi_hardware_pwm`` channel 0 driving the passive
    piezo. The PWM square wave is the tone: ``freq`` = pitch, ``duty`` =
    amplitude. Constructed only in :func:`sound_monitor` on real hardware
    (the import is lazy so this module stays import-safe on dev machines)."""

    def __init__(self) -> None:
        from rpi_hardware_pwm import HardwarePWM

        self._pwm = HardwarePWM(pwm_channel=PWM_CHANNEL, hz=PWM_HZ_DEFAULT)
        self._pwm.start(0)  # silent

    def tone(self, freq_hz: int, duty: float) -> None:
        """Sound one note. ``freq_hz <= 0`` or ``duty <= 0`` is a rest."""
        if freq_hz > 0 and duty > 0:
            self._pwm.change_frequency(freq_hz)
            self._pwm.change_duty_cycle(duty)
        else:
            self._pwm.change_duty_cycle(0)  # rest

    def silence(self) -> None:
        """Drive duty to 0 (stop sounding, keep the channel running)."""
        self._pwm.change_duty_cycle(0)

    def stop(self) -> None:
        """Release the PWM channel entirely."""
        self._pwm.stop()


# --- Producer helper ---


def request(sound_queue, earcon: Earcon) -> None:
    """Request an earcon, fire-and-forget. None-safe: on dev / rev3 boards
    ``sound_queue`` is ``None`` and this no-ops (after a debug log, so dev
    boxes still show intent). Stamps ``time.monotonic()`` for staleness."""
    logger.debug("sound: %s", earcon.value)
    if sound_queue is None:
        return
    sound_queue.put(PlayEarcon(earcon, time.monotonic()))


# --- Player ---


def play_earcon(driver: BuzzerPWM, earcon: Earcon, level: str) -> None:
    """Play an earcon to completion at ``level`` (non-preemptive). Each note
    sounds for its duration, then the buzzer is silenced. At ``level="Off"``
    every note's duty is 0, so this holds the rhythm silently."""
    for note in CATALOG[earcon].notes:
        driver.tone(note.frequency_hz, note_duty(level, note.volume))
        time.sleep(note.duration_ms / 1000.0)
    driver.silence()


def play_tone(
    driver: BuzzerPWM, frequency_hz: int, duration_ms: int, duty: float
) -> None:
    """Play a single raw tone, then silence. ``duty`` is an **absolute** PWM
    duty cycle (%), clamped to ``[0, MAX_DUTY]`` — it does NOT pass through the
    master-volume mapping. Used by the standalone player to probe the buzzer
    (find the resonant peak, choose duty values) independently of the catalog.
    """
    driver.tone(frequency_hz, max(0.0, min(MAX_DUTY, duty)))
    time.sleep(duration_ms / 1000.0)
    driver.silence()


def sound_monitor(sound_queue, shared_state, log_queue) -> None:
    """Process entry. Mirrors ``battery_monitor``: configure logging, build
    the hardware seam (exit if it fails — never fall back to fake audio), then
    serve the queue forever.

    ``shared_state`` is accepted for signature consistency / future use; v1
    reads nothing from it.

    Each pass blocks for one message, then drains everything else already
    queued (``get_nowait`` until empty). Within a batch we apply only the
    newest :class:`SetVolume` level and choose one play winner
    (:func:`select_winner`). The first level push (sent by main at startup) is
    applied silently; later pushes are user-initiated volume changes and play
    ``VOLUME_SAMPLE`` at the new level as audible feedback.
    """
    MultiprocLogging.configurer(log_queue)
    logger.debug("Starting sound monitor")

    try:
        driver = BuzzerPWM()
    except Exception as e:
        logger.error("Sound: BuzzerPWM init failed, disabled: %s", e)
        return

    # Process.terminate() / OS shutdown sends SIGTERM. Turn it into SystemExit
    # so the finally below silences and releases the channel — never leave the
    # buzzer driven (handoff watch-out #5).
    def _terminate(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _terminate)

    level = "Off"  # updated by the first SetVolume (sent by main at startup)
    level_initialized = False
    try:
        while True:
            first = sound_queue.get()  # block until something arrives
            pending = [first]
            try:
                while True:
                    pending.append(sound_queue.get_nowait())
            except queue.Empty:
                pass

            # Coalesce the batch: keep only the newest volume level; collect
            # all play requests for the drain policy.
            plays: List[Tuple[Earcon, float]] = []
            new_level: Optional[str] = None
            for msg in pending:
                if isinstance(msg, SetVolume):
                    new_level = msg.level
                elif isinstance(msg, PlayEarcon):
                    plays.append((msg.earcon, msg.requested_at))

            if new_level is not None:
                # The first push initializes the level silently; later pushes
                # are user volume changes and get audible feedback.
                play_feedback = level_initialized
                level = new_level
                level_initialized = True
                if play_feedback:
                    play_earcon(driver, Earcon.VOLUME_SAMPLE, level)

            winner = select_winner(plays, time.monotonic())
            if winner is not None:
                play_earcon(driver, winner, level)
    except (KeyboardInterrupt, SystemExit):
        logger.debug("Sound: exiting")
    finally:
        try:
            driver.stop()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Standalone player (CLI)
#
# A small command-line tool to play earcons and raw tones on the buzzer, for
# tuning the catalog and MASTER_DUTY by ear. Requires real hardware (PWM ch0);
# only ``--list`` works without it. Run from ``python/`` with:
#
#   python3 -m PiFinder.sound --list
#   python3 -m PiFinder.sound --earcon startup --level 5
#   python3 -m PiFinder.sound --all --level 3 --repeat 2
#   python3 -m PiFinder.sound --tone 4000:200:25        # FREQ:MS:DUTY
#   python3 -m PiFinder.sound --sweep 2000:6000:200:120 # START:STOP:STEP:MS
# ---------------------------------------------------------------------------


def _print_catalog() -> None:
    """Print the catalog (name, important/transient, total ms, notes)."""
    print("Earcon catalog:")
    for earcon, definition in CATALOG.items():
        kind = "important" if definition.important else "transient"
        notes = ", ".join(
            f"{n.frequency_hz}Hz/{n.duration_ms}ms@{n.volume}" for n in definition.notes
        )
        print(
            f"  {earcon.value:<14} [{kind:<9}] "
            f"{total_duration_ms(earcon):>4}ms  {notes}"
        )
    print(f"\nMaster levels (peak duty %): {MASTER_DUTY}")


def _parse_earcons(spec: str) -> List[Earcon]:
    """Resolve a comma-separated list of earcon names (or ``all``)."""
    if spec.strip().lower() == "all":
        return list(CATALOG)
    earcons: List[Earcon] = []
    known = ", ".join(e.value for e in CATALOG)
    for part in spec.split(","):
        name = part.strip()
        if not name:
            continue
        try:
            earcons.append(Earcon(name))
        except ValueError:
            raise SystemExit(f"Unknown earcon '{name}'. Known: {known}")
    return earcons


def _parse_ints(spec: str, count: int, usage: str) -> List[int]:
    """Parse a ``:``-separated list of exactly ``count`` ints, or exit."""
    parts = spec.split(":")
    if len(parts) != count:
        raise SystemExit(usage)
    try:
        return [int(p) for p in parts]
    except ValueError:
        raise SystemExit(usage)


def _run_cli(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m PiFinder.sound",
        description=(
            "Standalone earcon player for tuning the rev4 buzzer by ear. "
            "Requires real hardware (PWM ch0); only --list works without it."
        ),
    )
    parser.add_argument("--list", action="store_true", help="List the catalog and exit")
    parser.add_argument(
        "--earcon",
        help="Earcon name(s) to play, comma-separated (e.g. startup,keypress), "
        "or 'all'",
    )
    parser.add_argument(
        "--all", action="store_true", help="Play every catalog earcon in order"
    )
    parser.add_argument(
        "--level",
        default="5",
        help="Master volume level for earcons: Off,1,2,3,4,5 (default 5)",
    )
    parser.add_argument(
        "--tone",
        metavar="FREQ:MS:DUTY",
        help="Play one raw tone, e.g. 4000:200:25 (duty %% clamped to 0-50)",
    )
    parser.add_argument(
        "--sweep",
        metavar="START:STOP:STEP:MS",
        help="Sweep frequencies to find resonance, e.g. 2000:6000:200:120",
    )
    parser.add_argument(
        "--duty",
        type=float,
        default=25.0,
        help="Duty %% used by --sweep (default 25; clamped to 0-50)",
    )
    parser.add_argument(
        "--repeat", type=int, default=1, help="Repeat the whole sequence N times"
    )
    parser.add_argument(
        "--gap",
        type=float,
        default=0.5,
        help="Seconds of silence between earcons (default 0.5)",
    )
    args = parser.parse_args(argv)

    if args.list:
        _print_catalog()
        return

    if not (args.earcon or args.all or args.tone or args.sweep):
        parser.error("nothing to do: pass --earcon, --all, --tone, --sweep, or --list")

    if args.level not in MASTER_DUTY:
        parser.error(
            f"invalid --level {args.level!r}; choose one of {', '.join(MASTER_DUTY)}"
        )

    earcons: List[Earcon] = []
    if args.all:
        earcons = list(CATALOG)
    elif args.earcon:
        earcons = _parse_earcons(args.earcon)

    try:
        driver = BuzzerPWM()
    except Exception as e:
        raise SystemExit(f"Cannot open the buzzer (needs real hardware + PWM ch0): {e}")

    try:
        for _ in range(max(1, args.repeat)):
            if args.tone:
                freq, ms, duty = _parse_ints(
                    args.tone, 3, "--tone must be FREQ:MS:DUTY, e.g. 4000:200:25"
                )
                print(f"tone {freq}Hz {ms}ms duty {duty}%")
                play_tone(driver, freq, ms, float(duty))
            if args.sweep:
                start, stop, step, ms = _parse_ints(
                    args.sweep,
                    4,
                    "--sweep must be START:STOP:STEP:MS, e.g. 2000:6000:200:120",
                )
                duty = max(0.0, min(MAX_DUTY, args.duty))
                for freq in range(start, stop + 1, max(1, step)):
                    print(f"sweep {freq}Hz {ms}ms duty {duty}%")
                    play_tone(driver, freq, ms, duty)
            for earcon in earcons:
                print(f"earcon {earcon.value} @ level {args.level}")
                play_earcon(driver, earcon, args.level)
                time.sleep(args.gap)
    except KeyboardInterrupt:
        pass
    finally:
        driver.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _run_cli()
