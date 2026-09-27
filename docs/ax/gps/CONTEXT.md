# GPS

The GPS context acquires the observer's position and the wall-clock time from a satellite receiver, and publishes them as a **fix** and a **time** for the rest of the system. It runs as its own process behind one of three interchangeable **backends**, and — unlike every other subsystem process — it does not hold `shared_state`; everything it produces reaches the system through `gps_queue`.

## Language

### Processes and plumbing

**GPS process**:
The `multiprocessing.Process` named `"GPS"` spawned in `main.py`, running the selected backend's `gps_monitor`. It receives exactly three arguments — `gps_queue`, `console_queue`, `log_queue` — and notably **not** `shared_state`, which every other subsystem process does get. Any new fact the GPS process wants to publish therefore travels on `gps_queue`.
_Avoid_: GPS thread (it is a process, and the distinction decides what transports are available), GPS service, GPS daemon (that is **gpsd**, a separate OS-level thing).

**GPS backend**:
One of three interchangeable modules providing `gps_monitor(gps_queue, console_queue, log_queue)`: `gps_ubx` (parses raw UBX binary read from gpsd's socket — the default), `gps_gpsd` (consumes gpsd's own decoded TPV/SKY dicts via `gpsdclient`), and `gps_fake` (replays a recorded `.ubx` capture, or synthesises a slowly-improving fix). Chosen at startup from the `gps_type` **config_option**, which defaults to `ublox`. `gps_ubx` and `gps_fake` share the whole UBX decode path; `gps_gpsd` shares none of it.
_Avoid_: GPS driver, GPS mode, GPS source ("source" is the **location source**, a different thing).

**gpsd**:
The OS-level GPS daemon that owns the serial device. Both real backends talk to it — `gps_ubx` opens a raw socket to port 2947 and asks for binary passthrough, `gps_gpsd` uses its decoded JSON. Its serial baud rate is synced from the `gps_baud_rate` **config_option** at startup.
_Avoid_: the GPS daemon, the GPS service (ambiguous with the **GPS process**).

**gps_queue**:
The many-producer, single-consumer queue drained by the main loop, carrying `(tag, payload)` tuples. Despite living in `command_queues["gps"]`, it is an **inbox to the main process**, not a command channel *to* the GPS process — `UIGPSStatus` also publishes onto it, and nothing the main process puts there is ever read by the GPS process. There is no main → GPS channel at all.
_Avoid_: GPS command queue (it commands nothing), GPS channel.

### On the wire

**Frame**:
One delimited, checksum-verified UBX packet located in the incoming byte stream: sync bytes, class, id, length, payload, checksum. A frame is a *transport* unit and exists only on the UBX path — `gps_gpsd` receives decoded dicts and has no frames at all.
_Avoid_: packet, sentence (an NMEA word), UBX message (a frame may fail to become a **message**).

**Message**:
A decoded `dict` carrying a `class` key naming what it is: `NAV-SOL`, `NAV-SAT`, `NAV-DOP`, `NAV-TIMEGPS`, `NAV-PVT`, `NAV-SVINFO` on the UBX path, `TPV` and `SKY` on the gpsd path. Messages are what the dispatcher acts on. One **frame** yields at most one message.
_Avoid_: reading, record, sample.

**Marker**:
A synthesised **event** standing in for a **frame** that could not become a **message** — either its class/id has no registered parser (`?XXYY`, naming the two bytes) or its checksum failed (`?CKSUM`). Markers exist so that "the receiver is transmitting something we cannot read" is observable, instead of being indistinguishable from silence. The dispatcher ignores them; only the **comms row** consumes them. See [ADR 0032](../../adr/0032-ubx-parser-yields-undecodable-frames.md).
_Avoid_: error, unknown message (a marker is not a message), garbage.

**Event**:
The union of **message** and **marker** — everything the parser yields. The right word when talking about GPS link activity in general, because liveness is about events arriving, not about any of them being useful.
_Avoid_: message (when markers are included too), traffic, activity.

### The fix

**Fix**:
The position result published as `("fix", {...})`: latitude, longitude, altitude, **position error**, **lock**, **lock type**, and a **location source**. Emitted per qualifying NAV-SOL or NAV-PVT.
_Avoid_: position (reserve for the coordinate pair itself), solution (that is the Positioning context's plate-solve result — a *completely* different thing that also lives in `shared_state`).

**Lock**:
A sticky boolean meaning "this connection has, at least once, produced a fix whose reported error was under 50 km" (`MAX_GPS_ERROR`). It latches on and is never cleared for the life of a **GPS process** connection. It says the receiver got far enough to be believed once, not that the current fix is good.
_Avoid_: treating it as current-fix quality, "has signal", "locked on".

**Lock type**:
The receiver's own fix mode, `0`–`3`, carried through from the UBX `gpsFix` / gpsd `mode` field: no fix, dead-reckoning, 2D, 3D. Independent of **lock** — and it is `lock_type`, not `lock`, that `UIGPSStatus` tests to decide whether to say "GPS Locked".
_Avoid_: fix quality, lock strength, conflating with **lock**.

**Position error**:
The receiver's reported horizontal position uncertainty in metres (`ecefpAcc` from NAV-SOL, `hAcc` from NAV-PVT), stored as `error_in_m`. It gates whether a new fix is allowed to replace the stored **location** at all.
_Avoid_: accuracy (it is an error bound, and larger is worse), HDOP (a separate dimensionless quantity).

**Sats seen** / **sats used**:
Satellites the receiver is tracking, and the subset it used in the navigation solution. Published together as a `(seen, used)` tuple and always held so that `seen >= used`, since a satellite contributing to the solution is by definition being tracked. Several message classes carry only `used`, so the floor is what stops the display reading `0/9`.
_Avoid_: satellites in view (that is a wider set including ones not tracked), satellite count (which one?), nSat/uSat in prose.

**Location source**:
A string on the stored location recording where it came from — `GPS`, `WEB`, `MANUAL`, `CONFIG:<name>`, `Saved: <name>`, `replay`. It encodes **precedence**: a fix from the GPS process will not overwrite a location whose source is `WEB`, `MANUAL`, `replay`, or a `CONFIG:` entry. A user or a telemetry replay outranks the receiver.
_Avoid_: provider, origin, fix source.

### Diagnostics

**Comms row**:
The single `UIStatus` row reporting GPS link liveness, showing the name of the most recent **event** and the seconds elapsed since it arrived. A churning name means events are flowing; a frozen name with a rising age means the link died; `?XXYY` or `?CKSUM` mean bytes are arriving that we cannot decode; `--` means nothing has ever been received. Its age is derived from a **monotonic** stamp, never wall clock, because the GPS is what *sets* the wall clock.
_Avoid_: GPS status (that is the whole `UIGPSStatus` screen), message counter, heartbeat.

**Comms stamp**:
The monotonic reading recorded when a comms **event** is drained off **gps_queue** — taken by the *main* process, not the **GPS process**, so it can be subtracted from the reading the **comms row** takes when it renders. Only the event's name travels over the queue. The difference between the two is queue latency, well under one redraw.
_Avoid_: arrival time / timestamp unqualified (both read as wall clock), send time.

## Flagged ambiguities

- **"the GPS thread"** — there isn't one. It is a **GPS process**, and it is the only subsystem process that does not receive `shared_state`. Anyone reasoning about how to get data out of it from the "thread" framing will reach for shared memory that does not exist.
- **"GPS messages never leave the GPS process"** — they already leave three ways: decoded results on `gps_queue`, a `"GPS: Locked"` note on `console_queue`, and *every* parsed message logged at DEBUG through the multiproc log queue (there is a ready-made `logconf_gps.json` for exactly this). What is missing is a *live, on-device, no-restart* view, not egress.
- **`lock` vs `lock_type`** — different facts, and the UI mixes them. `lock` is a sticky "we believed a fix once this connection"; `lock_type` is the receiver's current 0–3 mode. `UIGPSStatus`'s headline reads `lock_type > 1` while its detail line reads `lock`, so the two can legitimately disagree on screen. Name which one you mean.
- **A worse fix is silently discarded** — the main loop only applies an incoming fix when its **position error** is *smaller* than the stored one. A receiver that degrades (antenna knocked, satellites lost) leaves the old position and its lock state standing indefinitely, with no on-screen signal that the fix is stale. This is deliberate but surprising.
- **`class` collides across contexts** — a GPS **message**'s `class` is a wire message type (`NAV-SOL`). In `gps_gpsd` it is gpsd's own tag (`TPV`). Neither is a Python class. Say "message class" or, better, name the message.
- **"solution"** — in this context a solution is the receiver's *navigation* solution. In [Positioning](../positioning/CONTEXT.md) a solution is a *plate-solve* result, and both are reachable from `shared_state`. Never use the bare word across the boundary.
- **Comms age must be monotonic, and from one process** — a GPS-derived timestamp sets the system clock, so an age computed from wall clock jumps or inverts the moment a fix lands. Monotonic solves that but introduces a second trap: `time.monotonic()`'s reference point is *undefined*, and on macOS it is process start, so subtracting one process's reading from another's yields the gap between their launches. On a dev machine that reads as a permanently several-second-old GPS link. Hence the **comms stamp** is taken by the main process on receipt: only the event name crosses the process boundary.

## Example dialogue

> **Dev:** I want to show whether we're getting GPS messages. Can I read the message list out of shared state?
>
> **Domain:** There isn't one, and the GPS process can't write to shared state anyway — it only gets three queues. Everything it publishes goes over `gps_queue` and the main loop puts it into shared state on its behalf.
>
> **Dev:** Fine, I'll send a command to the GPS process asking it to start reporting.
>
> **Domain:** You can't. `gps_queue` looks like a command queue because of where it's stored, but it only flows *into* main — the GPS process never reads it. There's no main-to-GPS channel at all. Publish unconditionally instead.
>
> **Dev:** So if the row is empty, the GPS is dead?
>
> **Domain:** Careful. Empty means no **event** has *ever* arrived. A dead link shows the last event's name frozen with a climbing age. And if you see `?0135` or `?CKSUM` churning, the receiver is very much alive — we just can't decode what it's saying, which is usually a baud rate or the wrong receiver.
>
> **Dev:** And if it says locked I can trust the position?
>
> **Domain:** Ask which "locked". `lock` latches the first time we believed a fix and never clears. `lock_type` is the receiver's current mode. And remember a worse fix never overwrites a better one, so a good position can outlive the conditions that produced it.
