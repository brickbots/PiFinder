# Sound (Audio Feedback)

The Sound context turns named user-/system-events into short audible cues on the rev4 PiFinder's **passive piezo buzzer**, driven by hardware PWM (channel 0, GPIO12). It is **best-effort, fire-and-forget** feedback — never a data channel and never something another subsystem blocks on. Gated on rev4 hardware presence, like [Battery](../battery/CONTEXT.md).

## Language

### Sounds

**Earcon**:
A named, recognizable short sound cue tied to an event — e.g. `startup`, `shutdown`, `keypress`, `error`. The unit a producer *requests* (by name); it carries no audio data on the wire. An earcon is an *identity* ("which event happened"), conveyed by pitch contour and rhythm, **not** a melody.
_Avoid_: "sound effect" as a wire payload (producers send a name, not notes), "tune"/"melody" (this buzzer can't carry one — see **resonance**).

**Note**:
The atomic unit an earcon is made of: a **frequency** (Hz), a **duration**, and an **intent volume**. An earcon is an ordered list of notes (and rests). Resolved to PWM steps *inside* the Sound context, never by the producer.
_Avoid_: "beep" (reserve for the colloquial whole-earcon sense), "tone" when you mean the structured note record.

**Intent volume**:
A per-note authored loudness **intention**, `0.0`–`1.0` (perceptual: "soft" → "loud"). It is *not* a duty cycle — the messy non-linear duty mapping lives in one place in the Sound context. Can only attenuate; it cannot make an off-resonance note as loud as a resonant one.
_Avoid_: "duty cycle" (an implementation output, not the author's intent), "amplitude".

### Request timing

**Important earcon** vs **transient earcon**:
A property of an earcon's definition. **Transient** earcons (`keypress`, navigation) are time-sensitive feedback: a request that arrives **stale** (older than its max-age) is discarded, because a cue that lands after the user has already seen the result is worse than silence. **Important** earcons (`startup`, `shutdown`, `error`, `low_battery`) are exempt from staleness and **win the drain** — a flood of transient requests can never bury one.
_Avoid_: "priority" (overloaded), treating staleness as an error condition (dropping a stale transient is normal, intended behaviour).

**Stale / max-age**:
A request is **stale** when the elapsed time since it was stamped exceeds its **max-age**. Staleness is measured on a **monotonic** clock so a GPS wall-clock step can't make queued requests look ancient or future-dated. Only transient earcons expire.
_Avoid_: "timeout" (no waiting is involved — it's an age test at drain time).

**Master volume**:
A single user setting that scales every earcon. One of a small set of discrete levels (`Off`, `1`–`5`); each level is a hand-tuned **peak duty cycle** for a full-intent note. A note's emitted duty is `master_peak × note.volume`, clamped to the `0–50%` usable range (50% is the buzzer's loudest; above it loudness falls off and is never emitted). The non-linearity of perceived loudness vs level is absorbed into the hand-tuned per-level numbers.
_Avoid_: "gain" (it's not a clean multiplier in dB), a separate "mute" flag (`Off` is a level).

### Hardware reality

**Resonance**:
The passive piezo is dramatically loudest at its **~4 kHz resonant peak** and much quieter away from it. Pitch and loudness are therefore *coupled*: the earcon catalog is designed near resonance and uses pitch contour for identity, not even-volume melody.
_Avoid_: assuming frequency and loudness are independent.
