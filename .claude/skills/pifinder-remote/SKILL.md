---
name: pifinder-remote
description: >-
  Run the PiFinder app headlessly and drive it like a user — launch it with no
  pygame window or physical display, send keypad presses to navigate menus,
  capture the 128x128 screen as a PNG, read live state (plate solve, location,
  IMU, SQM), and stop it cleanly. Use this whenever you need to actually
  operate or observe the running PiFinder UI rather than just read its code:
  "launch/start/run PiFinder", "navigate to <menu/screen>", "take a screenshot
  of PiFinder", "press UP/DOWN/SQUARE", "what's on the PiFinder screen", "what
  is it solving / where is it pointing", "check the UI shows X", "reproduce
  this UI bug", "drive the PiFinder interface", or "stop/shut down PiFinder".
  Also use it to verify UI-affecting changes by running the app and looking at
  the screen.
---

# Driving PiFinder headlessly

PiFinder normally renders to a physical OLED/LCD (or a pygame emulator window)
and is driven by a hardware keypad. This skill runs it in a **headless** mode —
no pygame, no SDL window, no hardware — while still rendering every frame, and
drives it entirely over PiFinder's HTTP API. That lets you launch the app,
navigate its menus, see exactly what's on screen, read its live state, and shut
it down, all from the command line.

Everything goes through one helper: **`scripts/pf_remote.py`** (Python standard
library only — runs under any `python3`; it finds and uses the PiFinder venv
itself when launching). Run `python3 <skill>/scripts/pf_remote.py -h` for the
full command list.

## The loop

```bash
S=.claude/skills/pifinder-remote/scripts/pf_remote.py   # adjust path as needed

python3 $S launch            # start cedar + headless PiFinder, wait for the API
python3 $S screen -o /tmp/pf.png   # capture the current 128x128 screen as PNG
python3 $S key DOWN DOWN RIGHT     # send keypad presses, in order
python3 $S status            # aggregated live state as JSON
python3 $S stop              # graceful shutdown, then guaranteed teardown
```

After `launch` succeeds, the other commands find the running instance (URL +
PIDs) from a small state file in the temp dir — you don't need to pass the URL.
**Read the PNG that `screen` writes** (use the Read tool on the path it prints)
to see the UI; that is how you "look at" PiFinder.

## Commands

| Command | What it does |
|---|---|
| `launch` | Starts `cedar-detect-server` then PiFinder headless (`-fh --camera debug --keyboard none --display headless -x`), in its own process group, and waits until `/api/status` answers. Records state for the other commands. |
| `screen [-o PATH]` | Saves `GET /api/screen` (the live 128×128 display) as a PNG and prints the path. |
| `key BTN [BTN ...]` | POSTs each button to `/api/key` in order (default 0.4s apart, `--delay` to change). |
| `status` / `solution` / `location` | Pretty-prints `GET /api/status` / `/api/solution` / `/api/location`. |
| `get PATH` | GETs any other endpoint, e.g. `get /api/imu`, `get /api/sqm`. |
| `stop` | Best-effort graceful `/api/stop`, then escalates to SIGTERM/SIGKILL on the process group so nothing is orphaned. |
| `kill` | Skips the graceful step; force-kills the recorded process groups (recovery). |
| `logs [-n N]` | Tails the captured PiFinder and cedar startup logs (first place to look if `launch` fails). |
| `ready` | Polls until the API answers; useful after a manual launch. |

## Keypad buttons

PiFinder has a small keypad. Pass these names to `key` (case-sensitive), or a
raw integer keycode:

- Directions / actions: `UP` `DOWN` `LEFT` `RIGHT` `PLUS` `MINUS` `SQUARE`
- Long press (held): `LNG_LEFT` `LNG_UP` `LNG_DOWN` `LNG_RIGHT` `LNG_SQUARE`
- Alt (function) variants: `ALT_UP` `ALT_DOWN` `ALT_LEFT` `ALT_RIGHT` `ALT_PLUS` `ALT_MINUS` `ALT_SQUARE` `ALT_0`
- Number keys: pass the digit as an integer, e.g. `key 1 2 3`

Navigation model: `RIGHT` (or `SQUARE`) generally drills into the highlighted
item, `LEFT` goes back, `UP`/`DOWN` move the selection, `LNG_LEFT` returns to
the top menu. After any input, take a fresh `screen` to confirm what happened —
the screen is the ground truth, menu order changes between versions.

## How it works (and why stop is built this way)

- **Headless rendering.** The launch passes `--display headless`, which selects
  the in-memory `DisplayHeadless` driver (`python/PiFinder/displays.py`, backed
  by `luma.core.device.dummy`). The UI render loop already calls
  `shared_state.set_screen()` beside every hardware draw, so the current frame
  is always available at `GET /api/screen` regardless of display driver. No
  pygame/SDL/X is needed.
- **Input.** `--keyboard none` runs a no-op keyboard process; `POST /api/key`
  injects into the same `keyboard_queue` the main loop reads, so menu
  navigation behaves exactly as with the real keypad.
- **Solving works headless.** With `--camera debug`, PiFinder cycles through
  sample frames and `cedar-detect-server` + the solver produce real plate
  solves, so `status`/`solution` return live RA/Dec/constellation.
- **Stopping is deliberately two-stage.** PiFinder is multi-process; its workers
  run bare `while True` loops, aren't daemonized, and don't watch a stop flag.
  Clean shutdown depends on `SIGINT` reaching the whole process group at once
  (what a terminal Ctrl-C does). `POST /api/stop` does that from inside the app,
  which reliably stops the worker processes — but the main process can still
  hang in its teardown (a multiprocessing-manager shutdown race). So `launch`
  starts PiFinder in its **own session/process group, isolated from the
  launcher**, and `stop` escalates with `SIGTERM`→`SIGKILL` on that group after
  a short grace period. `stop` returns as soon as the process is actually gone.
  This guarantees no orphaned processes even when the graceful path stalls.

## When startup fails

`launch` waits up to `--timeout` seconds (default 90) for the API. The **first**
launch in a fresh checkout rebuilds the catalog cache (~90s, one time); later
launches come up in a few seconds. If it times out:

1. `python3 $S logs` — read the PiFinder/cedar startup logs.
2. Confirm the venv exists (`python/venv` or `python/.venv`) and the object DB
   is present (`astro_data/pifinder_objects.db`).
3. The API binds port 80 when it can, else 8080; `launch` probes both and
   records the winner. Pass `--base-url http://host:port` to override.
4. If a previous run left something behind, `python3 $S kill` clears it.

## Notes

- Repo location is auto-detected (this skill lives under the repo). Override
  with `--repo /path/to/PiFinder` or the `PIFINDER_REPO` env var.
- This skill requires two small pieces of in-repo support that ship with it:
  the `headless` display driver and the `POST /api/stop` endpoint
  (`python/PiFinder/api_extensions.py`). They're already in this branch.
- The screen is 128×128 and rendered mostly in the red channel (PiFinder's
  night-vision palette); that's expected, not a rendering bug.
