# `PiFinder.bringup` — implementation plan

Bench validation for freshly assembled rev4 boards: one command, one screen, every
listed subsystem exercised while the builder watches. Product of a grilling session
against the domain docs — the glossary it uses is
[`docs/ax/bringup/CONTEXT.md`](docs/ax/bringup/CONTEXT.md).

## 1. What it is

```
$ python -m PiFinder.bringup
```

A **single process** that opens the panel directly, drives the keypad backlight and
buzzer, interrogates the IMU and charger, and scans the keypad matrix — reporting
everything on one live screen. It does **not** boot the application: no
`SharedStateObj`, no catalogs, no solver, no camera, no `MenuManager`. It runs on a
card with nothing configured yet and is ready in about a second.

Six **checks**, in three kinds (the distinction the exit status turns on):

| Check | Kind | What proves it |
|---|---|---|
| `SCREEN` | witnessed | Test patterns then the live dashboard — builder's eyes |
| `BACKLIGHT` | witnessed | Continuous brightness ramp — builder's eyes |
| `BUZZER` | witnessed | Startup earcon + one per keypress — builder's ears |
| `IMU` | **probed** | BNO055 answers its chip-identity register; quaternion moves when tilted |
| `CHARGER` | **probed** | BQ25895 part-number register reads `0b111`; live voltages decode |
| `SWITCHES` | **exercised** | Every populated matrix position observed closing |

Only **probed** and **exercised** checks gate the verdict and the exit status.
Witnessed checks are reported as *emitted* — the program drove the hardware; whether
light or sound came out is not something it can know.

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Relationship to the app | Standalone module, `python -m PiFinder.bringup` | Works on a bare card before catalogs/cedar-detect exist; `splash.py` is the precedent |
| Name | `bringup`, not `hw_test` | `hw_test.py` matches pytest's `*_test.py` discovery and reads as a test file inside the package; "bring-up" is the industry term and gives docs a noun |
| Keypad input | Raw matrix scan in `bringup` | Proves each *switch* and its row/col wiring; immune to chording/long-press/auto-repeat, which would otherwise mask faults |
| Matrix tables | Extracted to a new import-safe `PiFinder/keypad.py` | One source of truth for the wiring; `keyboard_pi` can't be imported off-Pi (`libinput`, `RPi.GPIO`) |
| Panel selection | **Fixed rev4 default**, `--display` override | `main`/`splash` derive the panel from the charger probe; on a board under bring-up that makes a dead charger look like a dead screen |
| Screen proof | Pattern sequence, then dashboard | Dashboard alone can't reveal offset/rotation, edge pixels or wrong channel order |
| Sound + backlight | Wired into the button test | Startup earcon proves the buzzer at once; a keypress earcon per closure re-proves it ~18×; a ramping backlight makes a dim string obvious |
| Verdict | PASS banner + exit status | Scriptable later without redesign |
| Scope | The six checks only | Camera/GPS/wifi are separate bench steps with different rigs |

Declined during grilling: an ADR for the panel decision (the rationale goes in the
module docstring instead), and rewriting the build guide (follow-up).

## 3. Files

| File | Change |
|---|---|
| `python/PiFinder/keypad.py` | **New.** Import-safe matrix tables + population maps |
| `python/PiFinder/keyboard_pi.py` | Read the tables from `keypad.py`; no behaviour change |
| `python/PiFinder/bringup.py` | **New.** The entry point |
| `python/tests/test_bringup.py` | **New.** Pure-logic and layout tests |
| `docs/ax/bringup/CONTEXT.md` | **New.** Glossary (done — this PR) |
| `CONTEXT-MAP.md` | Bring-up context + relationships (done — this PR) |
| `docs/ax/ui/CONTEXT.md` | Keypad layout corrected to 5 columns / both revs (done — this PR) |

## 4. `PiFinder/keypad.py` (new, import-safe)

`keyboard_pi.py` imports `libinput` and `RPi.GPIO` at module scope, so it cannot be
imported on a dev box — which rules out importing the tables from it, both for
`bringup` (which must run headless for layout work) and for unit tests. Lift the pure
data into its own module, importing only `KeyboardInterface` (which is import-safe):

```python
"""Keypad matrix wiring: the physical truth shared by the keyboard scanner
and bring-up. Pure data, import-safe everywhere (no RPi.GPIO, no libinput)."""

from PiFinder.keyboard_interface import KeyboardInterface as K

MATRIX_ROWS = [19, 17, 18, 22, 20]      # BCM, driven LOW one at a time
MATRIX_COLS = [16, 23, 26, 27, 21]      # BCM, read with pull-ups
POWER_GPIO = 15                          # direct, not in the matrix

KEYMAP      = [...]   # 25 entries, moved verbatim from KeyboardPi.__init__
ALT_KEYMAP  = [...]
LONG_KEYMAP = [...]

def position(row: int, col: int) -> int:
    """Matrix position -> keymap index."""
    return row * len(MATRIX_COLS) + col

# Population maps: which positions carry a switch on each revision.
# rev3: cols 0-3 of every row (17 switches, 3 NA holes).
# rev4: rows 0-3 of cols 0-3, plus ALL of col 4 — the directional cluster
#       moved off the bottom row and gained its own centre SQUARE (18).
REV3_POPULATED = frozenset(...)
REV4_POPULATED = frozenset(...)
```

`KeyboardPi.__init__` then becomes `self.rows = keypad.MATRIX_ROWS`, etc. Its derived
`square_keycodes` / `repeat_keycodes` comprehensions keep working unchanged, since
they read `self.keymap`.

**The population maps are the load-bearing new fact.** From the 25-entry keymap:

```
       col0  col1  col2  col3    col4
row0    7     8     9    (na)    UP     ┐
row1    4     5     6    PLUS    LEFT   │ col4 = the cluster
row2    1     2     3    MINUS   DOWN   │ added for rev4, with
row3   (na)   0    (na)  SQUARE  RIGHT  │ a centre SQUARE
row4    LEFT  UP    DOWN  RIGHT  SQUARE ┘
        └─ rev3 directional row ─┘
           (unpopulated on rev4)
```

rev4 = 13 (calculator pad) + 5 (col 4) = **18 switches, two `SQUARE`s**. Note that
`(4,4)` *is* populated on rev4 — only cols 0–3 of row 4 are rev3-only. Getting this
wrong in either direction breaks the verdict: too many expected and PASS never
arrives; too few and a dead switch passes silently. **Confirm against the first
board** (see §10).

## 5. `PiFinder/bringup.py` structure

Follows `sound.py`'s discipline — pure logic separated from thin hardware seams, so
the interesting parts are unit-testable off-Pi and every hardware import is lazy.

```
bringup.py
├── module docstring ......... carries the panel-choice rationale (no ADR)
├── pure logic (testable off-Pi, no imports beyond stdlib/PIL)
│   ├── parse_pwm_overlay(config_txt) -> dict[channel, gpio]
│   ├── GridState .............. seen/held sets, press/release edges
│   ├── CheckResult / Kind ..... probed | exercised | witnessed
│   ├── compute_verdict(results) -> bool     # witnessed excluded by construction
│   ├── grid_layout(display) -> GridLayout   # derives from resolution
│   └── format_summary(results) -> str
├── hardware seams (constructed only on real hardware)
│   ├── BacklightPWM ........... PWM ch1, mirrors sound.BuzzerPWM
│   ├── MatrixScanner .......... GPIO row/col scan + power line
│   ├── ImuProbe ............... wraps imu_pi.Imu
│   └── ChargerProbe ........... wraps battery_bq25895.BQ25895
├── rendering
│   ├── draw_patterns(display) ......... the witnessed screen sequence
│   └── draw_dashboard(display, state) . title + status rows + grid
└── main(argv) ....... argparse, lock, preflight, run loop, summary, exit code
```

### Reuse

| From | Used for |
|---|---|
| `displays.get_display(name)` | Panel driver; `--display` accepts every existing name (`ssd1333`, `ssd1351`, `pg_176`, `headless_176`…) |
| `display.fonts` / `display.colors` | Text metrics and the red mask, so bring-up looks like the product |
| `ui.layout.rows_below_titlebar` | Status-line y-positions |
| `ui.layout.center_box_row` | One call per grid row — replaces per-screen centring math |
| `sound.BuzzerPWM`, `play_earcon`, `CATALOG`, `Earcon` | Buzzer; earcons from the catalog, never raw tones |
| `battery_bq25895.BQ25895`, `REG14`, `EXPECTED_PN` | Charger comms + live decode |
| `imu_pi.Imu` | IMU; its `adafruit_bno055` constructor validates the chip id and raises on mismatch — that *is* the comms proof |
| `utils.acquire_single_instance_lock()` | Refuse to run while the service holds the device |
| `keypad.*` | Matrix wiring and population maps |

Not reusable as-is: `main.py`'s `init_keypad_pwm` / `set_keypad_brightness` depend on
a `HardwarePWM` global imported inside main's `__main__` block (`main.py:1284`), so
bring-up needs its own ~12-line `BacklightPWM` seam. That seam is a candidate answer
to the standing `TODO` at `main.py:78` ("Keypad pwm class that can be faked maybe?"),
but adopting it in `main` is out of scope here.

## 6. The screen

```
┌────────────────────────┐
│ BRING-UP        rev4   │  title bar (inverts to "PASS" on verdict)
│ IMU  ok  cal2 q+0.71   │  status rows — rows_below_titlebar(small font)
│ CHG  ok  4.02V  PG     │
│ SW   13/18      PWR ·  │
│ ┌──┬──┬──┬──┬──┐       │
│ │7 │8 │9 │  │^ │       │  5×5 grid — center_box_row per row
│ ├──┼──┼──┼──┼──┤       │
│ │4 │5 │6 │+ │< │       │  cell states:
│ ├──┼──┼──┼──┼──┤       │    unpopulated  nothing
│ │1 │2 │3 │- │v │       │    unseen       dim outline + label
│ ├──┼──┼──┼──┼──┤       │    seen         bright outline + label
│ │  │0 │  │□ │> │       │    held         filled, label knocked out
│ ├──┼──┼──┼──┼──┤       │
│ │  │  │  │  │□ │       │  row4: only col4 populated on rev4
│ └──┴──┴──┴──┴──┘       │
│        [ PWR ]         │  power switch, its own cell (GPIO15 direct)
└────────────────────────┘
```

Separating **held** from **seen** is deliberate: a switch that reads permanently
closed is a solder bridge, and a switch that closes but never releases is a mechanical
fault. Both are build defects a press-counter alone would score as a pass.

Geometry derives from the display instance (ADR 0009), never hardcoded — cell size
falls out of `(resY - grid_top - 5*gap) // 6`. Fits 128×128 (≈12 px cells) and
176×176 (≈18 px cells); a unit test asserts no overflow on both.

**Pattern sequence** (≈4.5 s at entry, `--no-patterns` to skip, `--pattern-loop` to
repeat forever for panel-only work):

1. Full-field fill — dead pixels, uniformity
2. 1 px border + corner ticks + centre cross — full extent, offset, rotation
3. R | G | B vertical stripes — channel order, catches a wrong-BGR or wrong panel part

Patterns draw raw RGB, bypassing the red `Colors` mask — the point is to prove all
three channels reach the glass, even though the product only ever shows red.

## 7. Checks in detail

**Pre-flight** (before anything else, reported on its own line)

- `/dev/i2c-1` present → IMU and charger can be reached at all.
- PWM routing, parsed from `/boot/config.txt` (and `/boot/firmware/config.txt`):
  `dtoverlay=pwm,pin=13,func=4` routes **ch1 → GPIO13** only; the buzzer needs
  **ch0 → GPIO12**, i.e. `dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4`.
  This matters because the Pi's PWM block always exposes two channels, so
  `HardwarePWM(pwm_channel=0)` **exports successfully and drives no pin** — a silent
  no-sound indistinguishable from a dead buzzer. Bring-up must say
  `PWM ch0 not routed to GPIO12 — buzzer cannot sound (add pwm-2chan)` instead of
  failing `BUZZER`. See §10: this repo's `pifinder_setup.sh` provisions only the
  single-channel overlay.

**SCREEN** (witnessed) — pattern sequence, then the dashboard is its own ongoing proof.

**BACKLIGHT** (witnessed) — `BacklightPWM` on ch1, sawtooth 0 → ~12 % → 0 over ~2 s,
stepped once per frame. A ramp beats a static level: a dim or partially-lit LED string
is obvious against a sweep and invisible against a fixed brightness. (12 % is main.py's
documented effective ceiling; re-confirm for rev4.)

**BUZZER** (witnessed) — `Earcon.STARTUP` once at entry at level `"5"`, then
`Earcon.KEYPRESS` on every new closure, so the buzzer gets re-proved ~18 times during
the switch sweep. Skipped with a clear reason if pre-flight says ch0 isn't routed.

**IMU** (probed) — construct `imu_pi.Imu()`; `adafruit_bno055` reads and validates the
BNO055 chip id in its constructor and raises on mismatch, so construction succeeding
*is* the comms proof. Then `imu.update()` per frame, showing calibration status and
the live quaternion so tilting the board visibly moves the numbers — that catches a
part that ACKs but sits in a bad mode, which a bare presence probe would pass.
PASS = constructed **and** at least one non-`None` quaternion.

Watch: `Imu.__init__` builds a `config.Config()`, which pulls in `equipment`/`locations`.
It tolerates a missing config file, so a fresh card is fine — but if it proves fragile
during bring-up, fall back to constructing `adafruit_bno055.BNO055_I2C(board.I2C())`
directly, which loses only the moving/threshold logic bring-up doesn't need.

**CHARGER** (probed) — construct `BQ25895()`, read `REG14`, check
`(reg14 >> 3) & 0b111 == EXPECTED_PN`. That identity check is stronger than the bare
ACK `hardware_detect` uses, and it is the right depth for bring-up. Then `read_state()`
about once a second for live battery/VBUS/SYS voltage and charge status.
**Strictly read-only**: `read_state()`'s one-shot ADC trigger is the sanctioned write
(ADR 0006); `apply_charging_config()` is never called — setting charge current belongs
to the monitor process (ADR 0017), not to a diagnostic.
PASS = part number matches.

**SWITCHES** (exercised) — the matrix scan mirrors `KeyboardPi.run_keyboard`: drive one
row LOW as an output, read all columns (pull-ups, active low), restore the row to
input. No debounce beyond the frame, no chord or long-press interpretation — bring-up
wants the raw edge. The power switch is read directly from `POWER_GPIO`, active low,
with no 1 s hold requirement (a brief tap lights it, which also keeps the press short).
PASS = every position in the revision's population map observed closed at least once,
power switch included.

Loop: scan at ~60 Hz like the shipping scanner; redraw at ~12 fps to keep SPI traffic
reasonable.

## 8. Lifecycle and guardrails

- **Single-instance lock.** Takes the same `utils.acquire_single_instance_lock()` as
  `main.py`, so it refuses to start while the service holds the panel, PWM and I²C —
  and says `stop the pifinder service first: sudo systemctl stop pifinder` rather than
  producing a garbled screen and confusing readings.
- **Never acts on the power switch.** No shutdown jump, no `jump_to_label`, and nothing
  anywhere near GPIO14 — pressing power during bring-up only lights a cell.
- **Never writes config**, never writes the charger's power path, never touches OTG/HIZ.
- **Ignores `Config` entirely** for its own behaviour: a board under bring-up has no
  user config yet. Consequence: it opens the panel unrotated, so a Bloom/Heart build
  shows the dashboard inverted — `--rotate {0,1,2,3}` covers that.
- **Cleanup in `finally`.** Both PWM channels stopped (buzzer silent, backlight off) and
  the panel blanked, on SIGINT/SIGTERM as well as normal exit — the buzzer must never be
  left driven.
- **Exit.** Ctrl-C ends the run; the summary prints to stdout and the exit status is 0
  when the verdict passes, 1 otherwise. Optional `--timeout SECONDS` for an unattended
  bench.

```
$ python -m PiFinder.bringup
PRE-FLIGHT  i2c-1 ok · pwm ch1→gpio13 ok · pwm ch0→gpio12 NOT ROUTED
SCREEN      emitted    3 patterns + dashboard          (witnessed)
BACKLIGHT   emitted    ramp 0-12% on pwm ch1           (witnessed)
BUZZER      skipped    pwm ch0 not routed              (witnessed)
IMU         PASS       BNO055 id ok, cal 2, q live     (probed)
CHARGER     PASS       BQ25895 pn=0b111, 4.02V, PG     (probed)
SWITCHES    FAIL       17/18 — (1,3) PLUS never closed (exercised)
VERDICT     FAIL
$ echo $?
1
```

## 9. Tests — `python/tests/test_bringup.py`, `@pytest.mark.unit`

Everything below runs off-Pi; the module must import with no `RPi.GPIO`, `board` or
`rpi_hardware_pwm` present, which is what keeps the hardware imports lazy.

1. `rev4` population map has 18 positions; `rev3` has 17.
2. Every populated position maps to a non-`NA` keymap entry (catches the two tables drifting).
3. `KeyboardPi` still sources its rows/cols/keymaps from `keypad.py` (guards the extraction).
4. `parse_pwm_overlay` — single-channel, `pwm-2chan`, absent, commented-out.
5. `compute_verdict` ignores witnessed results entirely; fails on a missing switch; fails on a probe failure; passes only when every gating check passes.
6. `GridState` press/release edges: repeat presses don't double-count; held ≠ seen; a stuck position stays held.
7. `grid_layout` fits within `resY` on `DisplayHeadless` (128), `DisplayHeadless176` and `DisplayHeadless320`.
8. `format_summary` renders each kind with the right label and never prints PASS/FAIL for a witnessed check.
9. `python -m PiFinder.bringup --help` succeeds with no hardware.

## 10. To confirm on the first board

These are assumptions the plan rests on that only hardware can settle:

1. **The rev4 population map.** The plan expects 18 switches including a second
   `SQUARE` at `(4,4)`. Commit `e82b809d` says the fix "enables repeat on **both**
   directional clusters", which could mean rev4 populates both the bottom row *and*
   col 4 (22 switches). If so, `REV4_POPULATED` changes — one constant, no redesign.
2. **`pwm-2chan`.** `pifinder_setup.sh:64` provisions only
   `dtoverlay=pwm,pin=13,func=4`. If a reference rev4 card's `/boot/config.txt` has no
   `pwm-2chan` line, the buzzer has never been routed to a pin and the setup script
   needs fixing — separate PR, and exactly the class of fault bring-up exists to name.
3. **The LTC2954 on a long power-button press.** ADR 0007 documents GPIO14 → KILL as
   the shutdown path; whether the controller *also* kills on a long button hold is
   unverified. If it does, document "tap, don't hold" in the builder instructions.
4. **Backlight duty range on rev4.** `main.py`'s "effective range seems 0-12" comment
   predates rev4; retune the ramp ceiling if the LEDs behave differently.
5. **Panel opens without the charger.** Pull the charger (or test a board with a dead
   one) and confirm `--display ssd1333` still brings the screen up — the entire reason
   the panel isn't derived from the probe.

## 11. Sequencing

- **PR 1 (this branch)** — docs only: the Bring-up glossary, the CONTEXT-MAP entry, and
  the rev3/rev4 keypad correction in the UI glossary. No code, no risk.
- **PR 2** — `PiFinder/keypad.py` extraction + `keyboard_pi.py` reading from it + tests.
  A pure data move with no behaviour change, landed on its own so any keypad regression
  is bisectable in isolation from the new tool.
- **PR 3** — `PiFinder/bringup.py` + `test_bringup.py`.
- **Follow-ups, not scheduled** — build-guide rewrite (replacing the manual "Tools >
  Status, then Name Search" procedure at `build_guide.rst:223`); `pifinder_setup.sh`
  PWM fix if item 2 above confirms it; adopting `BacklightPWM` in `main.py`.

## 12. Explicitly out of scope

Camera and solver validation (needs `cedar-detect` and a star target — a different
bench step), GPS, wifi, per-unit pass/fail record files, any menu entry in the running
app, and an ADR for the panel decision (rationale lives in the module docstring).
