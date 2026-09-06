# Voice notes on the LOG screen: feasibility study

Question asked: given a USB microphone plugged into a PiFinder, what would it take to
transcribe spoken observation notes on the logging screen?

Short answer: it is feasible, and speech recognition is nowhere near the hardest part. Two
of the obstacles have nothing to do with audio at all, and one of those two blocks the whole
idea until it is fixed: there is currently nowhere in an observation record to put a
sentence. The rest of the difficulty is CPU budget, accuracy on catalogue designations, and
getting a model onto every SD card.

Everything below was checked against the code on `main` as of 2026-09-06. File and line
references are to that state.

## Settled so far

Three things were decided in the session that produced this document, and the rest of it
assumes them:

- **This would ship to every PiFinder**, not just one bench unit. That makes distribution a
  first-class problem rather than a footnote, and it makes the typed free-text note more
  important than the spoken one, because most users will type. See section 6, WP5, and the
  new section 7.
- **Near-real-time is the requirement**, with other processing paused if that is what it
  takes. Sections 3 and 3a were rewritten to answer this. Short version: a transcript
  appearing one to three seconds after you stop talking looks achievable, live word-by-word
  captioning does not, and the first one is what a logging screen wants anyway. That
  reversed D2, which now transcribes on the spot rather than deferring.
- **Press-to-start and press-to-stop**, not hold-to-talk. The keyboard protocol stays as it
  is. See D5.
- **No code yet.** This document is the deliverable; nothing has been implemented.

---

## 1. The blocking discovery

**An observation has no free-text field to put a transcript in.**

`UILog.record_object()` (`python/PiFinder/ui/log.py:246`) builds this and nothing else:

```python
notes = {
    "schema_ver": 2,
    "transparency": ...,   # enum: NA / Excellent / Very Good / Good / Fair / Poor
    "seeing": ...,         # same enum
    "eyepiece": ...,       # "25mm Plossl" or "NA"
    "observability": ...,  # int 0-5
    "appeal": ...,         # int 0-5
}
```

That dict goes to `obslog.Observation_session.log_object()`, then to
`ObservationsDatabase.log_object()`, which JSON-dumps it into the `notes` TEXT column of
`obs_objects` (`python/PiFinder/db/observations_db.py:188`). Every value is a small enum
or a 0-5 integer. There is nowhere for a sentence to go.

So the first work package is a free-text note, with no audio involved at all. It ships on
its own, it is useful on its own, and without it transcription has no destination.

Two more facts about that column:

- `ObservationsDatabase` has **no update method**. Only `log_object` writes, and it only
  inserts. Any design where the transcript arrives after the log is saved needs a new
  write path.
- The web page renders notes unescaped. `server.py:1144` joins the dict into
  `"key: value<br>key: value"` and `views/obs_session_log.html:28` renders it with
  `| safe`. Today the only user-controlled value in there is the eyepiece name, so this is
  already a latent stored-XSS on an authenticated single-user page, which is about as
  harmless as stored XSS gets. Free-text notes would widen it considerably. Escape each
  value before joining and keep `| safe` for the `<br>` separators.

TSV export is fine, incidentally. `observations_as_tsv` drops the raw JSON into one cell,
and `json.dumps` escapes tabs and newlines inside the string, so a multi-line transcript
will not break the columns.

---

## 2. What else the code says

### The LOG screen has room

`UILog` draws five rows indexed 0-4 (SAVE Log, Observability, Appeal, Conditions...,
Eyepiece...). `key_right` acts on the selected row, number keys 1-5 set star ratings, and
`key_square` does nothing at all (`cycle_display_mode` is a bare `pass`). The marking menu
is declared with three empty options. There is space for a sixth row and a spare key.

### Sound cannot host the microphone

`docs/ax/sound/CONTEXT.md` describes the rev4 buzzer on hardware PWM channel 0, GPIO12,
and says outright that it is "best-effort, fire-and-forget feedback, never a data channel."
It is output only, by charter.

Searching the whole tree for `alsa`, `arecord`, `microphone`, `pyaudio` or `sounddevice`
returns nothing. Audio input is entirely new ground.

### There is no push-to-talk gesture

This one surprised me. `keyboard_pi.run_keyboard()` puts a single integer on
`keyboard_queue` per **completed** gesture:

- an ordinary key fires on release (`keyboard_pi.py:147`)
- `LNG_*` fires at the one-second mark while the key is still held, and the eventual
  release is swallowed by the `hold_sent` flag
- `ALT_*` fires on release while SQUARE is held

No key-down/key-up pair reaches the UI. Holding a button while you talk, which is the
gesture everyone imagines for this feature, cannot be built without changing the keyboard
protocol, and that change touches every screen. Design around press-to-start and
press-to-stop instead.

### Good precedents to copy

- A bundled native binary with an architecture suffix: `bin/cedar-detect-server-aarch64`,
  spawned by `solver.py:612` when nothing is already listening.
- A fake for every hardware seam: `gps_fake`, `imu_fake`, `battery_fake`, `camera_debug`,
  `keyboard_none`.
- Request/response across processes: the `alignment_command_queue` and
  `alignment_response_queue` pair in `main.py`.
- Interchangeable backends behind one interface: the three GPS backends.

### The domain has a gap here

Observation logging is not its own context. `docs/ax/catalog/CONTEXT.md` defines **Log
entry** and **Logged**, and states that "the observations DB is read-only from the Catalog's
perspective." Nothing owns the write side or the shape of the note payload. Adding voice
notes means deciding where that vocabulary lives, and I would put it in a new context
rather than stretching Catalog, which explicitly disclaims the write path.

### Hardware

rev3 is a Raspberry Pi 4B 2GB (`docs/source/BOM.rst:78`); rev4 is a CM4 (ADR 0034 gates the
poweroff overlay on `[cm4]`). Both give you four Cortex-A72 cores at 1.5GHz with NEON and
no accelerator. The BOM puts full-load draw at about 0.9A at 5V, with a rough hour of
runtime per 1000mAh.

rev4 exposes a USB-C **DATA** port for accessories (`docs/source/user_guide.rst:801`), so
there is somewhere to plug a mic. On rev3 you are using the Pi's own ports through the
shroud opening.

`hardware_detect.detect_capabilities()` ACK-probes I2C address 0x6A once at startup and
publishes `HardwareCapabilities(has_bq25895, has_buzzer)`, which is then immutable for the
life of the process. A USB microphone is hot-pluggable and has nothing to do with board
revision, so it does not belong in that record.

---

## 3. CPU budget, and why the published numbers mislead

The solver runs continuously. Capture, then cedar-detect in its own process over shared
memory, then a tetra3 solve, plus the integrator and the IMU. The PiFinder does not have
four idle cores; it has maybe one or two cores of genuine headroom.

My first pass at this section concluded there was no trustworthy number to design against.
That was true as far as it went, but it missed the reason the published numbers look bad,
and the reason turns out to be the most useful fact in this document.

### Whisper always processes 30 seconds

Whisper's encoder takes a fixed 30-second window. Anything shorter is zero-padded to fill
it. A 10-second note therefore costs exactly as much encoder time as a 30-second one, and
almost every discouraging Raspberry Pi benchmark is measuring a full 30 seconds of encoder
work no matter how short the clip was. Observation notes are five to twenty seconds. We
would be paying for silence.

Three ways out, and they compound.

**Scale the audio context to the actual utterance.** whisper.cpp exposes `audio_ctx`, and
[issue #1855](https://github.com/ggml-org/whisper.cpp/issues/1855) reports the effect of
setting it with `audio_ctx = (length_in_seconds / 30) * 1500 + 128`. On roughly 5.7-second
Common Voice clips with `base.en`, total processing went from 204 seconds to 60 seconds, a
3.4x speedup, and word error rate slightly improved (20.06 to 19.2) rather than degrading.
The known failure mode is that pushing `audio_ctx` too far from what the model was trained
on can send the decoder into repeating the last few tokens, so this wants bounds and a test.

**Or use a model that never pads.** [Moonshine](https://github.com/moonshine-ai/moonshine)
is built for exactly this problem: its compute scales with actual audio length instead of a
fixed window. From the [paper](https://arxiv.org/html/2410.15608v1), Moonshine Tiny is 27.1M
parameters against Whisper tiny.en's 37.8M, claims a 5x compute reduction on a 10-second
segment, and posts a slightly better average WER (12.66% vs 12.81%). Moonshine Base at 61.5M
parameters beats Whisper base.en on WER (10.07% vs 10.32%) while costing less than base.en
does. The English models are MIT licensed, and the project ships a portable C++ core on
ONNX Runtime that lists Raspberry Pi as a target. The smaller model also helps the SD-image
problem in section 7.

The honest caveat: the Moonshine paper benchmarks on an H100, not on ARM. The architectural
argument for why it should win on short clips is sound and the Pi support is claimed by the
project, but nobody in these sources has published Pi 4 numbers. That is a WP2 question.

**And give it all four cores for the burst.** More on that below, because it is cheaper than
it sounds.

### What the arithmetic suggests

Treat the following as arithmetic, not measurement. Whisper tiny's encoder at full context
is roughly 35 GFLOP (four layers, d=384, 1500 frames). Four Cortex-A72 cores at 1.5GHz
realistically deliver somewhere in the region of 10 to 15 GFLOPS on quantized GEMM, which
puts the encoder alone at about three seconds for a full 30-second window. Scale
`audio_ctx` for a 10-second note and the quadratic attention terms fall away faster than
the linear ones, dropping the encoder to roughly a third of that. Add a few hundred
milliseconds of decoding for the thirty or so tokens such a note produces.

That lands at **one to two seconds for a ten-second note on four dedicated cores**. If I am
off by a factor of three, which is entirely possible given how badly the Pi 4 is served by
its memory bandwidth, it is four to six seconds. Moonshine should beat both.

So the answer to "can this be near real time" is yes, with an important distinction in the
next section.

**None of this removes the need for WP2.** It changes what WP2 is testing from "is this
hopeless" to "which of these two engines wins, and by how much."

---

## 3a. Two different things called "near real time"

**Live captioning**, where words appear as you speak, is hard on a Pi 4. whisper.cpp's
streaming example needs a reduced context and a sliding window, it re-encodes overlapping
audio repeatedly, and quality suffers. Moonshine v2 introduces a streaming encoder that
attacks this directly, but it is new and unproven here.

**Fast turnaround**, where you stop talking and the text appears a second or two later, is
very achievable on the numbers above.

For a logging screen, the second one is what matters, and I would argue it is the better
interface regardless. Watching a transcript rewrite itself mid-sentence while you are dark
adapted at the eyepiece is worse than a brief "transcribing" indicator followed by a clean
result you can accept or redo.

### On pausing other processing

You offered to pause other work, and it is a cheaper trade than you may think, for a reason
worth spelling out.

Nothing needs pausing while recording. Capturing 16kHz mono audio is nearly free. The only
contended window is the inference burst after the user stops talking, which on these numbers
is one to three seconds.

During that window the telescope is not moving. The user has just finished observing and is
standing there dictating. The IMU keeps dead-reckoning the pointing throughout, so pausing
the solver does not lose the position, it just briefly stops refreshing it. A two-second
gap in solve cadence while the scope sits still is close to free.

That makes four dedicated cores a realistic assumption rather than an optimistic one.

---

## 4. Accuracy, and the one genuinely clever idea

General-purpose speech recognition will mangle "NGC 7331", "Collinder 399", "Barnard 33"
and "Struve 2816". It will do fine on "faint fuzzy patch, needed averted vision, hint of a
dust lane," which is what people actually dictate at the eyepiece, so this may matter less
than it first appears.

Two mitigations exist, and one of them is specific to this device:

- Vosk accepts a restricted vocabulary or grammar, so you can bias hard toward catalogue
  designations, at some cost to free prose.
- whisper.cpp accepts an initial prompt that biases decoding. **The PiFinder already knows
  which object you are logging.** Feeding the object's designations and popular names
  ("M 31", "NGC 224", "Andromeda Galaxy") into the decoder as context costs nothing and
  should measurably help on exactly the words that are otherwise hardest. `UILog` holds
  `self.object`, so the data is right there.

Neither fixes it completely, which leads to the central design decision.

---

## 5. Design decisions, with recommendations

### D1: the audio is the artifact, the transcript is derived

Keep the WAV. Never delete it as a side effect of transcribing. The transcript can be
regenerated later with a better model, corrected by hand, or ignored, and the recording of
what you actually said at the eyepiece is the thing with lasting value.

This one decision resolves most of the tension elsewhere. It makes imperfect accuracy
survivable, it makes deferred transcription safe, and it means a failed or skipped
transcription still leaves the user with something. It is hard to reverse (once you have
shipped a version that discards audio, those recordings are gone) and it deserves an ADR.

### D2: transcribe on the spot, with a deferred fallback

**Revised.** My first draft said transcribe after saving, on the assumption that inference
would take long enough to be intolerable at the eyepiece. Section 3 undermines that
assumption. At one to three seconds for a typical note, making the user wait is fine, and
showing them the text while they can still do something about it is a much better feature
than backfilling it into a record they have already walked away from.

So: stop recording, show a progress indicator, transcribe with the solver paused, and put
the text in front of the user with the option to accept, redo, or edit before saving. That
also removes the need for WP4 to exist before the feature is honest, though a web-side edit
is still worth having.

Two things to keep from the original design:

- Keep the deferred path as the fallback. If WP2 comes back slower than hoped, or a
  particular note is unusually long, degrade to saving immediately and filling the text in
  later rather than blocking. That still needs the new `ObservationsDatabase` update method,
  and a startup sweep that re-queues any voice note whose transcript never landed because
  the unit was powered off mid-job. Without that sweep, "deferred" quietly means "sometimes
  never."
- Set a hard ceiling on how long the UI will wait. If inference overruns it, fall back to
  deferred rather than leaving the user staring at a spinner in the dark.

Pausing the solver for the burst is discussed in section 3a. It costs almost nothing here
because the scope is stationary and the IMU carries the pointing.

### D3: put the transcript in the notes JSON, bump to `schema_ver: 3`

Add a `note` key for free text and a `voice_note` key holding a filename. Not a new column.
The notes dict is already the extension point, the web renderer iterates keys generically,
and TSV export carries the JSON through unchanged. Readers need to tolerate v2 entries.

The one thing this gives up is searchability. If you ever want "find the night I mentioned
a dust lane," JSON in a TEXT column is the wrong home and you would want a real column or
FTS. I would still take the JSON key now and revisit if search becomes a request.

### D4: name the audio file by a minted UUID, not the observation id

`log_object` only returns the observation id after the insert, so naming files after it
means recording to a temporary name and renaming. Minting a UUID at record time and storing
it in the notes JSON avoids that, and survives a database rebuild.

Suggested location: `~/PiFinder_data/voice_notes/<session_uuid>/<uuid>.wav`. At 16kHz mono
16-bit that is roughly 1.9MB per minute, so thirty twenty-second notes cost about 20MB a
night. Keep them by default, expose them for download on the web session page, add a
retention setting later if anyone complains.

### D5: a new "Voice Note..." row on LOG, opening its own screen (settled)

Index 5 on the existing list, matching the "Conditions..." and "Eyepiece..." idiom. The new
screen starts recording on RIGHT, stops on RIGHT, cancels on LEFT, and auto-stops at a
timeout and after a few seconds of silence.

Rejected: hold-to-talk, because of the keyboard protocol finding in section 2. Changing that
protocol would touch every screen, and the `hold_sent` and `alt_sent` bookkeeping in the scan
loop is delicate enough that the regression risk is not worth the nicer gesture. Rejected for
now: the marking menu, because a primary action should not hide there, though it would make
a fine shortcut later once people know the feature exists.

Because there is no release event to stop on, the two auto-stops are not polish, they are
load-bearing. A user who walks away from a recording screen must not fill the SD card. Cap
the duration hard (sixty seconds is my suggestion) and stop on sustained silence.

### D6: do not extend `HardwareCapabilities`

That record is derived from a board-revision probe at startup and is immutable afterwards.
A USB mic is neither rev-linked nor static. Let the voice process enumerate ALSA capture
devices at startup and on request, and hide or disable the LOG row when there is no mic.
Add `voice.enabled` and `voice.device` config keys, following the camera and GPS backend
settings.

If the mic is unplugged mid-recording, fail that recording with an on-screen message and
keep the log entry. Best-effort, in the spirit of the Sound context.

### D7: a new Voice process

Capture and recognition both live there, with a command queue in and a response queue out,
following the alignment queue pair. Inference must never run in the main process, which owns
the UI loop, and capture must not be interrupted by screen redraws.

### D8: pluggable recognition backend, English only to start

Define one interface, ship one implementation, pick it with the bench in WP2.

**Revised prior: Moonshine first, whisper.cpp second, Vosk third.** Now that D2 wants a
synchronous transcript, latency matters again, and Moonshine is the only candidate whose
architecture is actually built for short utterances. It is also smaller than whisper tiny.en
(27.1M parameters against 37.8M), scores marginally better on WER, and is MIT licensed for
English. whisper.cpp with a scaled `audio_ctx` is the fallback and the better-proven
ecosystem. Vosk drops to third: it streams well but its accuracy on free prose is the
weakest of the three, and streaming is not what this interface needs.

English only for v1, with a `voice.language` key reserved. PiFinder ships translations
including Chinese, so this is a real limitation and the docs should say so rather than let
people discover it by dictating a note and getting nonsense back. Worth noting for later
that Moonshine publishes non-English models, but under a non-commercial licence for the
legacy non-streaming ones, so the licensing needs rechecking before anyone promises
multilingual support.

### D9: recording is explicit, and audio never leaves the device

A microphone at a star party picks up the people around you. No always-listening mode, no
voice activation to start a recording, a visible on-screen indicator while recording, and
files that stay local unless the user downloads them. One line in the user guide, one in
the ADR.

### D10: a fake backend, so the whole flow is testable

`voice_fake.py` returns a canned transcript after a delay, selected under `-fh`. That makes
the entire path testable on a dev box and screenshottable through the pifinder-remote skill:
row, record screen, pending state, transcript arriving, notes rendering. The pure-logic
seams worth unit tests are the v2-to-v3 notes read, the silence and timeout state machine,
and the file naming.

### Terminology, for whenever this reaches a CONTEXT.md

- **Voice note**: a user-initiated audio recording attached to one log entry. The durable
  artifact.
- **Transcript**: text derived from a voice note. Always regenerable, never authoritative.
- **Note text**: the free-text field on a log entry. A transcript is one way to fill it, the
  keypad is another. A note is not a voice note.
- Avoid "recording" on its own, which collides with log entries and observation records.
  Avoid "dictation", which implies live word-by-word. Qualify "capture" as "audio capture"
  every time, because the Camera context uses the bare word for images throughout.

---

## 6. Work packages

**WP0. Free-text note on a log entry.** No audio. Bump to `schema_ver: 3`, add a `note`
key, add a "Note..." row on LOG wired to the existing `UITextEntry` (the multi-tap keypad
already exists in `ui/textentry.py`), render it as a block on the web session page, escape
the values before joining, tolerate v2 entries on read. Small. Do this first whether or not
voice ever happens.

**WP1. Voice note capture.** Audio, no recognition. New `voice.py` with the Voice process
and an ALSA capture seam, plus `voice_fake`. New `UIVoiceNote` module and the LOG row. WAV
files under `~/PiFinder_data/voice_notes/`. Web playback and download. Config keys. Medium:
a new hardware seam, a new process, a new UI module. Ships alone, and "record a spoken memo
against an observation" is genuinely useful with zero recognition risk.

**WP2. The bench.** No longer a go/no-go on whether this is possible, now a choice between
engines and a check on the arithmetic in section 3. Build whisper.cpp for aarch64 and get
Moonshine's C++ core running on ONNX Runtime. Record ten clips of real observing speech
through the actual microphone in the actual conditions, five to twenty seconds each.

Measure, for each engine:

- wall time against audio duration, at one, two and four threads
- whisper.cpp with default `audio_ctx` and with it scaled per issue #1855, to confirm the
  3.4x holds on ARM and to find where the decoder starts repeating tokens
- accuracy on catalogue designations specifically, with and without decoder priming from the
  logged object's names
- the same runs with the solver paused and with it running, plus the effect on solve rate
- CPU temperature across a sustained run of twenty notes, since the case does not breathe
- current draw delta on a rev4

The target to beat is roughly two seconds for a ten-second note on four cores. My arithmetic
says that is achievable; this is where it gets confirmed or corrected.

**WP3. Transcription.** The backend interface, the chosen engine, the fake. The deferred
queue and the startup sweep for orphaned recordings. Decoder priming from the logged
object's designations. The new `ObservationsDatabase` update path. Medium to large.

**WP4. Correction.** A web route to edit a log entry's note, and a re-transcribe button.
Small to medium, and I would argue WP3 is not honest without it.

**WP5. Distribution.** The binary into `bin/` with an architecture suffix, following
cedar-detect. Then the model file, which is the awkward part, and section 7 covers why.
Both the Raspberry Pi OS image and NixOS need it. Unknown effort until WP2 picks the engine.

**WP6. Docs.** A CONTEXT.md for the new context, the ADR on audio-as-artifact, the ADR on
deferred transcription (possibly the same one), a user guide section including which
microphone to buy, and the privacy line.

---

## 7. What "ships to everyone" adds

Deciding this is a product feature rather than a bench experiment changes four things, and
two of them are heavier than any of the code above.

**The model has to be in the image.** Downloading on first use is not an option. A PiFinder
in a field is usually its own access point with no route to the internet, and the first use
is exactly when someone is standing in the dark trying it out. So the model has to be
present on a fresh card: roughly 40MB for Vosk small, 75MB for `tiny.en`, and less for
Moonshine Tiny, which has about a quarter fewer parameters than `tiny.en` and quantizes the
same way. Git is a poor home for a blob that size and `astro_data/` is already large. Worth
considering: a release asset fetched at image-build time rather than tracked in the repo,
which keeps clones small and still gives every unit the file. This needs settling before
WP3, not after. Moonshine winning the bench would make this materially easier.

**ONNX Runtime is a new dependency if Moonshine wins.** whisper.cpp is a self-contained
binary in the `bin/cedar-detect-server` mould. Moonshine's portable core needs ONNX Runtime
for aarch64, which is a heavier thing to package on both Raspberry Pi OS and NixOS. Weigh
that against the speed advantage rather than assuming it away.

**English only is a shipped limitation, not a detail.** PiFinder has translated UI including
Chinese, and `tiny.en` and `vosk-model-small-en-us` are English models. Multilingual `tiny`
is the same size but noticeably worse at English, so there is no free upgrade. The honest
move is to say so plainly in the docs and in the menu, rather than let a German or Chinese
user find out by dictating a note and getting nonsense back. If that is unacceptable, the
feature may need to be English-gated at the config level.

**Someone has to recommend a microphone.** "Assuming a USB microphone is plugged in" is fine
for a study and not fine for a shipped feature. Users will ask what to buy, and a bad answer
generates support load: ALSA device naming varies, cheap USB mics vary wildly in gain and
noise floor, and outdoor night use adds wind. This wants one named part in the BOM that has
actually been tried, plus a fallback path when the enumerated device is not the one the user
expected. On rev4 the mic goes in the DATA port; on rev3 it goes in a Pi USB port through
the shroud opening, which is a different physical story and needs its own line in the docs.

**Recording other people becomes a real concern.** One person recording themselves is their
own business. Shipping a microphone feature to a community that observes in groups is not.
D9 (explicit recording only, visible indicator, nothing leaves the device) stops being a
nicety and becomes the thing that makes the feature defensible.

The consequence for sequencing: WP0 gets more valuable and WP3 gets more expensive. Typed
notes serve every user in every language on every board revision with no new hardware, no
model file, and no privacy question.

---

## 8. Risks and kill criteria

Graded by what WP2 measures for a ten-second note on four paused-solver cores:

- Under about two seconds, build it synchronously as D2 now describes.
- Two to six seconds, still build it, but the progress indicator has to be good and the
  deferred fallback needs to be real rather than theoretical.
- Over about ten seconds, drop to deferred only, and expect people to find it disappointing.
- Over thirty seconds, or measurably damaging the solve rate even with the solver paused,
  kill on-device recognition. WP1 alone still gives you downloadable recordings, so "record
  now, transcribe on a laptop" remains a complete feature, just a less magical one.

Watch for the token-repetition failure mode if the `audio_ctx` route is taken. It degrades
into gibberish rather than into slowness, which is harder to notice in testing and much
worse in the field.

If designations come back mangled often enough that every transcript needs hand-editing,
the honest framing is "audio memos with a rough searchable index", not "voice notes", and
WP4 stops being optional.

If sustained inference costs meaningful battery runtime on a rev4, gate it behind a setting
and default it off.

---

## 9. What I would actually build

WP0 and WP1. Free-text notes plus voice memos. No new binaries, no model files, no CPU
risk, no accuracy problem, and it is a coherent feature that people would use. Everything
about transcription sits on top of that and can be decided later, on evidence from WP2,
without any of it being wasted work.

Now that this is a shipped feature, I would go further and say WP0 is the one that has to be
excellent. A typed note works for every user, in every language, on both board revisions,
with nothing plugged in. Voice is an accelerator on top of it for the people who want it. If
WP0 is good and WP2 comes back ugly, you have still shipped the feature that most people
were actually asking for when they said they wanted to record what they saw.

That said, the section 3 rewrite makes me more optimistic about the voice half than I was.
The reason Whisper looks bad on a Pi is that it processes thirty seconds whether you spoke
for thirty seconds or five, and both ways around that are cheap. If the bench confirms the
arithmetic, this ends up being a genuinely nice feature rather than a compromise, and the
hard problems go back to being the ones in sections 1, 4 and 7: where the text lives, whether
it spells "NGC 7331" correctly, and how the model reaches every SD card.

## Next step

Nothing here is committed to code. Two independent starting points, and WP2 does not block
WP0:

- **WP0** needs no decisions beyond what is written above. It is the safe, useful half.
- **WP2** needs a board, a microphone and an evening. Its most valuable single measurement
  is Moonshine Tiny against whisper tiny.en with scaled `audio_ctx`, on a ten-second clip,
  four threads, solver paused. That one number decides the shape of everything downstream.

---

## Sources for the performance claims

- [whisper.cpp issue #1855, variable `audio_ctx` gives ~3x on short clips](https://github.com/ggml-org/whisper.cpp/issues/1855),
  the source of the 204s to 60s figure and the WER comparison
- [Moonshine paper, arXiv 2410.15608](https://arxiv.org/html/2410.15608v1), the source of
  the parameter counts, the 5x claim for a 10-second segment, and the WER table
- [Moonshine on GitHub](https://github.com/moonshine-ai/moonshine), for the MIT licence,
  the C++ ONNX Runtime core, and the claimed Raspberry Pi support
- [whisper.cpp discussion #166, "Real-time transcription on Raspberry Pi 4"](https://github.com/ggml-org/whisper.cpp/discussions/166)
- [vosk-api on GitHub](https://github.com/alphacep/vosk-api)
- [Interpreting speech with a Raspberry Pi, Dr John's Tech Talk](https://drjohnstechtalk.com/blog/2022/11/interpreting-speech-with-a-raspberry-pi/)

Treat all of them as indicative only. None of these sources measures either engine on a
Cortex-A72, and the Moonshine paper benchmarks on an H100. The number that matters is the
one measured on a PiFinder.
