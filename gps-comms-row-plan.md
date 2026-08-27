# GPS comms row — implementation plan

**Goal:** answer "are we receiving GPS messages?" at a glance, on the device, with no restart and no second machine.

**Shape:** one row on the STATUS screen naming the most recent GPS **event** and how long ago it arrived.

```
GPS MSG TIMEGPS  0.4s
```

## What the row tells you

| On screen | Meaning |
|---|---|
| `SOL` / `DOP` / `TIMEGPS` churning, age near 0 | Healthy. The name changing frame to frame is itself the liveness signal — readable across a dark field without parsing digits. |
| `?0135` churning | Receiver is transmitting, but in a dialect we have no parser for. Wrong receiver, or a u-blox variant emitting IDs we don't register. |
| `?CKSUM` churning | Bytes arriving corrupted. Baud mismatch (`gps_baud_rate` is user-editable) or bad wiring. |
| name frozen, age climbing | The link died. The name tells you what it was doing when it stopped. |
| `--` | Nothing has *ever* been received this session. |

All four failure modes discriminated in one 21-character row. Today every one of them looks identical from anywhere above the parser.

## Decisions taken (and why)

1. **Live instrument, not a log view.** Every parsed message is *already* logged at DEBUG and there is a ready-made `logconf_gps.json`, but reaching it means switching log config, restarting the app, reproducing the fault, then reading a text file from another device. Unusable in the field.
2. **Capture at the frame layer, not just the message layer.** `_parse_ubx` silently drops any class/id it has no parser for, so "unintelligible" and "absent" are currently the same observation.
3. **One readout covering both backends.** `gps_gpsd` has no frames at all — its message half works unchanged, its frame-level events simply never occur.
4. **A menu item, not a key chord.** Originally scoped as SQUARE on the status screen; landed as its own discoverable, translatable entry. In the end the readout collapsed into a single status row, so no new screen is needed at all.
5. **Age + last event name, not a rate.** u-blox emits in per-epoch **bursts**, so a one-second window alternates between roughly 5 and roughly 10 and never settles. Age needs no window, is immune to burstiness, and reports *when* a dead link died — which a rate cannot.
6. **The parser yields markers for undecodable frames.** See [ADR 0032](docs/adr/0032-ubx-parser-yields-undecodable-frames.md).

## Rejected

- **A ring buffer of recent messages in `shared_state`.** The GPS process does not receive `shared_state` — it gets `(gps_queue, console_queue, gps_logqueue)` and nothing else, so this needs a new process argument. Worse, `UIStatus.update()` runs at the full 30 fps target with no throttle, so a whole-buffer copy back through the manager proxy would run 30×/second.
- **A dedicated GPS debug screen.** Designed in full, then dropped: a single row answers the actual question, and the screen would have been a second thing to navigate to while cold.
- **On-demand capture (press a key to start).** There is no main → GPS channel. `gps_queue` looks like one because it lives in `command_queues["gps"]`, but it flows only *into* main. Always-on also wins on merit: the age is already correct the instant you look, with no warm-up.
- **A once-per-second aggregate.** Would freeze the event name for a whole second and quantise the age, destroying the churn signal the design rests on.

## Implementation

### `PiFinder/gps_ubx_parser.py`

- `_parse_ubx`: for an unregistered `(class, id)`, return `{"class": f"?{msg_class:02X}{msg_id:02X}"}` instead of `{"error": "Unknown message type"}`, so the existing `if "class" in parsed` guard lets it through.
- `parse_messages`: on checksum mismatch, `yield {"class": "?CKSUM"}` alongside the existing WARNING.

Reserve the `?` prefix for markers. No real message class may start with it.

### `PiFinder/gps_comms.py` — new

`CommsPublisher(gps_queue, clock)`, shared by all three backends so the row means the same thing whichever is running. Holds the rate-cap state and does the `put`.

### `PiFinder/gps_ubx.py` — `process_messages`

Publish one comms event at the top of the `async for` loop, before the dispatch chain, so *every* event counts including ones we parse but don't act on:

```python
now = clock()
comms.publish(msg_class, now)
```

- Send the **raw** class (`NAV-TIMEGPS`); presentation belongs to the UI.
- Payload `("comms", class_name)` — the name only. See the stamping watch-out below.
- One clock reading per event, shared with the NAV-SAT freshness window, so the two agree on when a message arrived.
- **Rate-cap forwarding to ~20/s.** A resync storm can yield markers far faster than real messages arrive, and the `.ubx` replay path runs with `wait=0`. 20 Hz is well past perceptible against a 30 fps redraw, and it bounds worst-case queue traffic. This caps *reporting*, not parsing.

Steady-state cost is a handful of pipe writes per second against backpressure thresholds of 10 and 50, on a queue the main loop drains to empty 30×/second. The throttles only bite when the main loop is already stalled, where slowing GPS is the intended behaviour.

### `PiFinder/gps_gpsd.py`

Same publish in the `dict_stream` loop, using `time.monotonic()` and the same cap. Note the existing `filter=["TPV", "SKY"]` means this path can only ever report those two classes — the row is a weaker instrument on gpsd, and deliberately so rather than widening the filter as a side effect.

### `PiFinder/gps_fake.py`

The `.ubx` replay path reuses `process_messages` and gets this free. Add a publish to the synthetic branch too (class `FAKE`) so the row is live under `-fh` and the feature is developable without hardware.

### `PiFinder/state.py`

`gps_comms()` / `set_gps_comms()` and a `self.__gps_comms = None`, shaped exactly like the existing `sats` pair.

### `PiFinder/main.py`

One branch in the existing `gps_queue` drain, which is also where the event gets its stamp:

```python
if gps_msg == "comms":
    shared_state.set_gps_comms((gps_content, time.monotonic()))
```

### `PiFinder/ui/status.py`

- Add `"GPS MSG"` to `status_dict`, positioned after `"GPS LCK"` to group the four GPS rows. The key is exactly 7 characters, which is the width `_render_row` pads to. Status keys are untranslated literals throughout, so no `_()` — consistent with every existing row.
- Format in `update_status_dict` from `shared_state.gps_comms()`:
  - `None` → `"--"`
  - strip a leading `NAV-`: `TIMEGPS` and `POSECEF` (7) are the longest, versus `NAV-TIMEGPS` (11) which would not fit
  - age from `time.monotonic() - stamp`, bucketed to stay ≤ 5 chars: `<100s` → `47.2s`, `<100m` → `12m`, else `2h`

Base font is 21 chars on the 128 panel (`width=6`), key padded to 7, so the value column is **14**. Worst case `TIMEGPS 47.2s` is 13. The 176 panel gets 29, so it is only ever roomier. If a value ever does overflow, the row's existing horizontal scroller catches it rather than truncating.

## Tests

- **`test_gps_ubx_parser.py`** — an unregistered class/id yields `?XXYY`; a corrupted checksum yields `?CKSUM`. No existing test touches either branch (the one `"error"` assertion covers a short-payload SVINFO case), so nothing needs rewriting.
- **`test_gps_ubx_dispatch.py`** — extend the existing `run_messages` helper to capture `("comms", …)` puts. Assert one publish per event; assert the rate cap suppresses a burst, driven by the `FakeClock` already wired into `process_messages`; assert markers publish without disturbing the `(seen, used)` counts.
- **`test_status_scroll.py`** (or a sibling) — reuse the existing headless-display fixture for the formatter: `None` → `--`, `NAV-` stripping, age bucketing at each boundary, and **a width regression guard** asserting the rendered row fits `fonts.base.line_length` for every message class we can emit, on both panel resolutions.

## Watch-outs

- **The age stamp must be `time.monotonic()`, never wall clock.** GPS is what *sets* the system clock, so a wall-clock age jumps or inverts the moment a fix lands. This is the single easiest thing to get wrong here and it fails in exactly the situation the feature exists to diagnose.
- **...and both readings must come from the same process.** The first cut stamped in the GPS process and subtracted in main, on the theory that `CLOCK_MONOTONIC` is system-wide on Linux. It is — but `time.monotonic()`'s reference point is explicitly *undefined*, and on macOS it is process start, so the dev-machine row read a steady ~4s stale on a fake GPS publishing every 0.5s. Caught by running it, not by the tests. The stamp is now taken by main on receipt; only the name crosses the boundary.
- **`gps_queue.qsize()` raises `NotImplementedError` on macOS**, so the `.ubx` replay backend cannot run there at all (pre-existing, in both `gps_fake.emit` and `process_messages`' backpressure check). Exercise the replay path by driving `process_messages` directly, or on a Pi.
- `?` is reserved for markers.
- The gpsd path is limited to TPV/SKY by an existing filter.

## Follow-ups (not in scope)

- Surface `gps_comms` on the web status page / `/api/current-selection` — the web server already holds `shared_state`, so it is nearly free, and "read me your GPS MSG row" is a good support question.
- User-guide line documenting how to read the row.
