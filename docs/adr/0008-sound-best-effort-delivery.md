# Sound is best-effort: monotonic-stamped requests, stale transients dropped, latest-wins delivery

The Sound context delivers **earcons** (short audible cues on the rev4 buzzer) **fire-and-forget**. A producer never blocks and never learns whether its cue played. Each request carries a `time.monotonic()` timestamp; the player drains its whole queue at once, **discards stale transient requests** (older than a small max-age), and plays only the **newest survivor**. **Important** earcons (`startup`, `shutdown`, `error`, `low_battery`) are exempt from staleness and win the drain so a flood of transient requests can't bury them. Playback is **non-preemptive** — an earcon always finishes; a newcomer never interrupts mid-cue.

The driving constraint is **synchronisation, not completeness**: a `keypress` beep that lands after the user has already seen the screen change is worse than silence, and a backlog of queued beeps drifts permanently out of step with the user's actions. So the design optimises for "the sound you hear matches the thing you just did," accepting that some cues are dropped.

`time.monotonic()` (not `time.time()`) is load-bearing: PiFinder **slews the system wall-clock when GPS gets a fix** (the `time_force` path). Wall-clock stamps would make every queued request look ancient (all dropped) or future-dated (never dropped) the instant the clock steps. Monotonic time is immune to clock steps and comparable across processes on the same host.

## Considered options

- **Best-effort, latest-wins, monotonic staleness (chosen).** No backlog, cues stay in sync with user actions, and the protocol is a one-way `put()` — no acks, no producer blocking.
- **Faithful FIFO (play every request in order).** Rejected: a burst of keypresses queues a train of beeps that plays out long after the keys were pressed — exactly the desync we're avoiding. (The main loop already coalesces rapid keypresses to one per iteration, so a faithful queue would mostly back up on longer earcons.)
- **Preemptive playback (interrupt a playing earcon).** Deferred, not rejected: earcons are <1 s so nobody waits long, and aborting between notes adds real complexity. Revisit only if a genuinely urgent cue must cut off a long one.
- **Wall-clock (`time.time()`) timestamps.** Rejected: the GPS clock step breaks staleness entirely (see above).

## Consequences

- **Dropped beeps are normal, not bugs.** A future reader watching `select_winner` discard requests, or debugging "my cue didn't play," should know this is intended. Staleness is an age test at drain time, not an error condition.
- **Shutdown needs the one delivery guarantee the model otherwise lacks.** Because best-effort can't promise the `shutdown` cue plays before the GPIO14 power latch cuts power (see [ADR 0007](./0007-gpio-poweroff-latch.md)), the shutdown chokepoint (`callbacks.shutdown`) **requests the cue and then waits its catalog-computed duration + a margin** before invoking `shutdown now`. This bounded wait is a deliberate consequence of best-effort meeting a hard power-off, not a stray `sleep`.
- **Producers must stamp `time.monotonic()`** (done for them by the `request()` helper) and must not assume a cue played.
- The trade-off is revisitable per-earcon: the `important` flag already carves out the "must not be dropped" cues; a future need for guaranteed *transient* delivery would mean reopening this decision.
