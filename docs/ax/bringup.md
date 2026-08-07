# Bring-up: bench validation of a freshly assembled board

A **bring-up run** is the first power-on validation of a newly assembled
board. One command drives the screen, the keypad backlight and the buzzer,
interrogates the IMU and the charger, and watches the keypad while the
builder presses every switch — all on one live screen.

It deliberately does not start the application: no `SharedStateObj`, no
catalogs, no solver, no camera, no `MenuManager`. So it runs on a card that
has only just been imaged, it is ready in about a second, and a board with
no camera fitted still brings up everything else.

Run one after assembling or reworking a board, and before a unit is
configured or shipped. It is bench tooling, not field diagnostics: a
finished unit misbehaving under the stars is a different problem.

- `PiFinder/bringup.py` — the whole tool, one module.
- `PiFinder/keypad.py` — the matrix wiring, the keymap and the population maps.

Glossary: [`bringup/CONTEXT.md`](./bringup/CONTEXT.md). This document is
internal — the published manual does not cover bring-up.

---

## 1. Running a run

The application holds the panel, both PWM channels and the I²C bus, so stop
it first. A run refuses to start while the service is up rather than
fighting it for the hardware.

```bash
sudo systemctl stop pifinder
cd ~/PiFinder/python
python3 -m PiFinder.bringup
```

The run opens with three full-screen patterns, about a second and a half
each, then settles onto the dashboard and stays there. Press every key, tilt
the board, watch the grid fill in, and end the run when satisfied.

A run assumes a rev4 board. `--revision rev3` selects both the right set of
switches and the right panel for a v3 board. Bloom and Heart builds mount
the screen upside down relative to the others, so they want `--rotate 2`.

The panel is never derived from a hardware probe. `main.py` and `splash.py`
pick theirs from `hardware_detect`, which probes for the BQ25895 — charger
present means rev4, so use the 176×176 SSD1333. That rule is exactly wrong
for a board under bring-up, where a dead or unsoldered charger would make a
perfectly good screen look dead too.

## 2. Pre-flight: the card, not the board

Before anything is driven, the run prints one line describing how the
**card** is provisioned — whether the I²C bus is enabled, and whether each
PWM channel is routed to the pin its consumer needs:

```text
PRE-FLIGHT  i2c-1 ok | pwm ch1->gpio13 (backlight) ok | pwm ch0->gpio12 (buzzer) ok
```

This line comes first because a misprovisioned card and a bad board look
identical from the outside. A PWM channel that the kernel has exported but
muxed to no pin makes a perfectly good buzzer silent, and a builder who
reaches for a soldering iron at that point will desolder a healthy part.

So read the pre-flight before reading anything else. `NOT ROUTED` or
`MISSING` is a fault in the card's `config.txt`, not in the soldering.
Checks that depend on something the pre-flight found missing are reported as
`skipped` rather than failed — the run did not verify that part, and it will
not blame the board for the card.

Cards provisioned by `pifinder_setup.sh` hit this today. The script writes
`dtoverlay=pwm,pin=13,func=4`, routing channel 1 (backlight) only, while the
rev4 buzzer is on channel 0 / GPIO12 — so a fresh install reports
`pwm ch0->gpio12 (buzzer) NOT ROUTED` and the buzzer stays silent with no
other complaint. Tracked as
[#579](https://github.com/brickbots/PiFinder/issues/579). Until it is fixed,
replace that line in `/boot/firmware/config.txt` (`/boot/config.txt` on
older Raspberry Pi OS releases) with the two-channel form and reboot:

```text
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
```

## 3. The six checks

A run reports on six named checks, and each is a different kind of claim.
The kind says who established the result, and therefore how much it is
worth.

A **probed** check is one the program answers on its own, by talking to the
part. An **exercised** check is one the builder drives and the program
confirms. A **witnessed** check is one the program can only *emit* — it
drives the hardware, and the builder is the sensor.

| Check | Kind | What happens |
| --- | --- | --- |
| `SCREEN` | witnessed | Three full-screen patterns, then the live dashboard |
| `BACKLIGHT` | witnessed | A continuous brightness ramp on the keypad LEDs |
| `BUZZER` | witnessed | A startup tone, then one tone per switch closure |
| `IMU` | probed | The BNO055 answers its chip identity and produces a live quaternion |
| `CHARGER` | probed | The BQ25895 answers its part-number register; voltages decode |
| `SWITCHES` | exercised | Every populated switch is observed closing at least once |

The screen patterns are worth watching closely, because the dashboard alone
cannot reveal what they show. A full white field exposes dead pixels and
uniformity. The second draws a one-pixel border, corner ticks, a solid block
in the top-left corner only and a centre cross — offset, rotation, a
mirrored panel and clipped edges all become obvious against it. The third
sweeps red, green and blue stripes, which catches a wrong colour order or
the wrong panel part; the product only ever shows red, so the stripes
deliberately bypass the red mask to prove all three channels reach the
glass.

The backlight sweeps rather than sitting at a fixed level, because a dim or
partly-lit LED string is obvious against a ramp and invisible against a
steady brightness.

The IMU row shows `cal0 q ----` until the sensor reports calibration. Leave
the board still for a moment, then tilt it: once a live quaternion appears
the check passes. A part that ACKs on the bus but never fuses a reading does
not pass, which is exactly the failure a bare presence probe would miss.

Charger access is read-only. `read_state()`'s one-shot ADC trigger is the
only sanctioned write ([ADR 0006](../adr/0006-battery-read-only-telemetry.md));
`apply_charging_config()` belongs to the monitor process
([ADR 0017](../adr/0017-battery-fast-charge-config.md)), not to a diagnostic.

### 3.1 The verdict

The verdict is computed over the probed and exercised checks only, and it is
what the process exit status reports. When it passes, the title bar inverts
and reads `PASS`, so the result is readable from across the bench.

Witnessed checks never contribute. The run reports them as `emitted` — it
drove the panel, the LEDs and the buzzer, and whether light or sound came
out is not something it is in a position to know. A passing verdict means
the IMU and charger answered and every populated switch closed. It says
nothing at all about the screen, the backlight or the buzzer; those are the
builder's to judge.

A gating check that was `skipped` does not pass either. The run did not
verify that part, and saying `PASS` would claim it did.

## 4. The dashboard

The live screen carries a title bar, three status rows and the switch grid.

The title bar reads `BRING-UP` on the left and the board revision on the
right, and inverts to `PASS` when the verdict passes. Below it:

```text
IMU  ok  cal3 q+0.71
CHG  ok  4.02V BAT
SW   10/18      PWR *
```

`IMU` shows the calibration figure and the leading term of the live
quaternion. `CHG` shows whether the charger was identified, the battery
voltage it reports, and whether the board is running on external power
(`PG`) or on the battery (`BAT`). `SW` counts how many populated switches
have been observed closing, and marks the power switch with `*` once it has
been tapped. A part that never answered shows `--` and the reason.

Geometry is derived from the display instance
([ADR 0009](../adr/0009-resolution-flexible-ui-hybrid.md)), never hardcoded,
so the dashboard lays out on every panel bring-up supports.

## 5. The switch grid

The grid below the status rows has one cell per **matrix position** — one
`(row, column)` coordinate in the scanned keypad matrix. Bring-up reports
positions rather than key names on purpose: more than one position can send
the same key, so "the UI received SQUARE" would not say which joint
conducted.

Each cell carries a single character naming the key that position sends: the
digits, `+` and `-`, `#` for SQUARE, and `^ v < >` for the four directions.
The grid is the wiring matrix, not a picture of the keypad, so the letters —
not the shape — are what to read. On a rev4 board:

```text
          col 0   col 1   col 2   col 3   col 4

  row 0     7       8       9               ^
  row 1     4       5       6       +       <
  row 2     1       2       3       -       v
  row 3             0               #       >
  row 4                                     #

                    PWR
```

The power switch is wired to its own line rather than into the matrix, so it
has no matrix position and gets a wider cell of its own below the grid.

A cell is drawn dimly until that switch has been seen closing, brightly once
it has, and filled solid while it is held down. Seen and held are kept apart
deliberately: a position that reads permanently closed is a solder bridge,
and one that closes but never releases is a mechanical fault. A press
counter alone would score both as good.

Sweep the whole keypad, including a tap of the power switch, and every cell
should end up bright. Anything still dim is a switch that never closed.

Two positions send SQUARE on rev4 — the calculator pad's own button at row
3, and the joystick centre at row 4 — so both have to be pressed for the
grid to fill.

A position that carries no switch but closes anyway is drawn with `?` and
reported as `unexpected`. That does not fail the run, since the population
map rather than the board may be what is wrong, but it is never silently
dropped.

### 5.1 Blank cells are not faults

The matrix is scanned identically on every board revision, but revisions
populate different subsets of it, and a position that carries no switch is
simply not part of the run.

On rev4 the bottom row is empty except for its last cell, because rev4 has
no bottom directional row: the directional control moved into the right-hand
column. On a v3 board the opposite holds — the bottom row carries the four
arrow buttons and the right-hand column is empty. Either way the run counts
closures only against the switches that revision actually has: 18 on rev4,
17 on v3. Blank cells are not dead switches, and are not to be chased with
an iron.

### 5.2 The rev4 joystick is one component

On rev4 the five populated positions in the right-hand column are the five
contacts of a **single 5-way joystick** — four directions plus a centre
press — not five separate switches.

This matters when one of them fails to register. The grid says *which
contact* is not conducting, but the part to rework is one joystick: reflow
its joints, and replace the whole component if reflowing does not fix it.
Reading those five cells as five switches sends a builder hunting for a part
that is not on the board.

On a v3 board the four directions really are four separate switches along
the bottom row, each its own part.

> The glossary describes this column in **switch** language ("rev4 carries a
> right-hand column instead, with its own centre `SQUARE` (18 switches)")
> against a definition of *switch* as one physical pushbutton. That is a
> known terminology gap, not a licence to repeat it here.

## 6. Ending a run

A run is open-ended and keeps reporting until it is ended, in one of three
ways.

**Hold the power switch for a second.** This is the one for a bench with no
terminal in sight. The power cell fills a bar — `[#---]` through `[####]` —
for the whole second, so the boundary is visible and an accidental hold can
be released before it arms. At the threshold the screen reads `SHUTTING
DOWN`, a tone plays and the card is shut down cleanly. Pulling power on a
mounted filesystem is how a builder corrupts an image somewhere between the
first board and the tenth.

A *tap* is a different thing from a hold, and both are wanted: a tap is all
the `SWITCHES` check needs, and registers on the first scan that sees it.
The power switch is the only one whose duration means anything.
`--no-power-shutdown` removes the gesture entirely; a tap still counts.

The threshold is one second, matching `keyboard_pi.run_keyboard`'s power
threshold, so the same press ends a bring-up run and opens the shutdown menu
in the running application.

**Press Ctrl-C**, with a terminal in front of you.

**Set a time limit** with `--timeout SECONDS` and the run ends by itself
after that long — useful when working through a batch of boards.

Whichever way it ends, the buzzer is silenced and the backlight darkened on
the way out.

The power hold runs the same `sudo shutdown now` that `sys_utils.shutdown()`
runs, spelled out rather than imported so the tool still starts on a card
with nothing configured. It never touches the power-off latch: GPIO14 is the
kernel's to drive at power-off
([ADR 0007](../adr/0007-gpio-poweroff-latch.md)). If the shutdown request
fails — on a card whose `sudo` rules do not allow it — the run says so
rather than swallowing it, and the board is still up.

## 7. Reading the summary

When the run ends it prints the pre-flight line again and one line per
check:

```text
SCREEN     emitted   3 patterns + dashboard                 (witnessed)
BACKLIGHT  emitted   ramp 0-12% on pwm ch1                  (witnessed)
BUZZER     emitted   startup + keypress earcons             (witnessed)
IMU        PASS      BNO055 id ok, cal 3, q live            (probed)
CHARGER    PASS      BQ25895 pn=0b111, 4.02V, BAT           (probed)
SWITCHES   PASS      18/18                                  (exercised)
VERDICT    PASS
```

The exit status is 0 when the verdict passes and 1 when it does not, so a
run can be scripted into a batch workflow.

A failing run names what it found. Here one switch never closed, and the
position is spelled out along with the key it sends:

```text
SWITCHES   FAIL      17/18 - (2,4) DOWN never closed        (exercised)
VERDICT    FAIL
```

Three distinctions are worth holding on to when reading a summary:

- `FAIL` on a probed or exercised check points at the **board** — a joint, a
  missing part, a wrong part.
- `skipped` points at the **card**. Fix the provisioning, reboot and run
  again; nothing is wrong with the hardware until a run with a clean
  pre-flight says so.
- `emitted` is neither a pass nor a failure. It means the run drove that
  hardware. Whether the screen lit, the keypad glowed and the buzzer sounded
  is what the builder was watching for.

## 8. Options

| Option | What it does |
| --- | --- |
| `--revision` | Board revision being brought up: `rev4` (default) or `rev3` for a v3 board. Sets both the switch population map and the default panel |
| `--display` | Open a specific panel instead of the revision's own. Rarely needed |
| `--rotate` | Quarter-turns to rotate the screen, added to the panel's own orientation. Bloom and Heart builds want `2` |
| `--no-patterns` | Skip the screen patterns and go straight to the dashboard |
| `--pattern-loop` | Loop the patterns forever, for panel-only work. Ctrl-C to stop |
| `--backlight-max` | Peak duty percentage of the backlight ramp. Default 12 |
| `--volume` | Buzzer volume for the tones: `Off` or `1`–`5`. Default 5 |
| `--no-power-shutdown` | Do not end the run and shut down when the power switch is held. A tap still counts toward the switch check |
| `--timeout` | End the run after this many seconds instead of waiting |

`python3 -m PiFinder.bringup --help` prints the current list.

## 9. Gotchas

- **A run refuses to start while the service is up.** It takes the
  single-instance lock; otherwise the screen garbles and every reading is
  suspect. `sudo systemctl stop pifinder` first.
- **The buzzer seam does not consider the revision.** `Hardware.open`
  decides from the pre-flight alone, so a `--revision rev3` run on a card
  that routes channel 0 will happily drive a buzzer that a v3 board does not
  have and report `BUZZER emitted`. Witnessed means witnessed.
- **Only three tones are ever emitted**: `STARTUP` when the dashboard comes
  up, `KEYPRESS` on every closure, `SHUTDOWN` on the power hold. The sound
  catalog also defines `ERROR` and `SOLVE_LOCK`, but nothing wires them
  ([#581](https://github.com/brickbots/PiFinder/issues/581)) — there is no
  error tone to listen for.
- **Nothing here is translated.** The module never performs the `_()`
  install `main.py` does, so adding `_()` calls would `NameError` at
  runtime. The audience is the builder, not the observer.
- **The scan keeps no interpretation.** No debounce beyond the frame, no
  chording, no long-press, no auto-repeat: every one of those behaviours can
  mask a faulty switch, so bring-up wants the raw edge.
- **A seam that will not open does not end the run.** A board whose charger
  is dead must still bring its screen up and still let the builder sweep the
  keypad, so each failure is recorded and the rest carries on.
