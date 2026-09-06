# Voice notes on the LOG screen: feasibility study

Question asked: given a USB microphone plugged into a PiFinder, what would it take to
transcribe spoken observation notes on the logging screen?

Short answer: it is feasible, but speech recognition is the smallest part of the job.
Three of the four hard problems have nothing to do with audio, and one of them blocks the
whole idea until it is solved.

Everything below was checked against the code on `main` as of 2026-09-06. File and line
references are to that state.

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

## 3. The real risk: CPU

The solver runs continuously. Capture, then cedar-detect in its own process over shared
memory, then a tetra3 solve, plus the integrator and the IMU. The PiFinder does not have
four idle cores; it has maybe one or two cores of genuine headroom.

I went looking for a number I could design against and did not find a trustworthy one.
The canonical whisper.cpp thread on this,
[discussion #166, "Real-time transcription on Raspberry Pi 4"](https://github.com/ggml-org/whisper.cpp/discussions/166),
demonstrates `ggml-tiny.en.bin` with a reduced audio context on three threads but publishes
no audio-duration-versus-processing-time figures, and one commenter reports "several tens of
seconds for a 3 second long wav file" in non-streaming mode. Secondary write-ups claim
roughly two to three times faster than real time for tiny on a Pi 4, but they are
content-farm grade and I would not bet a design on them. Vosk's own material claims
real-time streaming on a Pi 3 or 4 with the 50MB small model, which is more plausible
because the model is far smaller, and one hobbyist writeup reports 6.6 seconds for a test
clip once the model is warm.

All of those numbers, even if accurate, are measured on an otherwise idle Pi. Ours is not
idle.

**So: bench it on the actual board with the solver running, before committing to anything
downstream.** That measurement is the go/no-go for the whole transcription half of this
project, and it is cheap to run. Details in WP2.

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

### D2: transcribe after saving, not before

Pressing SAVE Log writes the entry immediately with a reference to the audio file and no
transcript yet. The voice process transcribes at low priority and fills the text in
afterwards.

The alternative is making the user stand at the eyepiece watching a frozen screen while a
Pi chews through inference, and risking the observation itself if that goes wrong. Not
worth it. The cost is that users cannot immediately verify the text, which is what WP4
(editing) is for, and what keeping the audio makes tolerable.

This needs the new `ObservationsDatabase` update method noted above, plus a startup sweep
that re-queues any voice note whose transcript never landed because the unit was powered
off mid-job. Without that sweep, "deferred" quietly means "sometimes never."

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

### D5: a new "Voice Note..." row on LOG, opening its own screen

Index 5 on the existing list, matching the "Conditions..." and "Eyepiece..." idiom. The new
screen starts recording on RIGHT, stops on RIGHT, cancels on LEFT, and auto-stops at a
timeout and after a few seconds of silence.

Rejected: hold-to-talk, because of the keyboard protocol finding in section 2. Rejected for
now: the marking menu, because a primary action should not hide there, though it would make
a fine shortcut later once people know the feature exists.

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

Define one interface, ship one implementation, pick it with the bench in WP2. Prior
expectation: Vosk wins on CPU and latency, whisper.cpp wins on prose accuracy, and because
D2 makes latency mostly irrelevant, that tilts toward whisper.

English only for v1 (`tiny.en`, or `vosk-model-small-en-us`), with a `voice.language` key
reserved. PiFinder ships translations including Chinese, so this is a real limitation and
the docs should say so rather than let people discover it.

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

**WP2. The bench, which is the go/no-go.** Build whisper.cpp for aarch64 and set up Vosk.
Run `tiny.en` and `vosk-model-small-en-us` against ten clips of real observing speech,
recorded through the actual microphone in the actual conditions. Measure wall time against
audio duration, at one, two and four threads, both with the solver idle and with it running.
Record the effect on solve rate, the CPU temperature, and the current draw delta on a rev4.
Then decide. Nothing downstream should be built before this runs.

**WP3. Transcription.** The backend interface, the chosen engine, the fake. The deferred
queue and the startup sweep for orphaned recordings. Decoder priming from the logged
object's designations. The new `ObservationsDatabase` update path. Medium to large.

**WP4. Correction.** A web route to edit a log entry's note, and a re-transcribe button.
Small to medium, and I would argue WP3 is not honest without it.

**WP5. Distribution.** The binary into `bin/` with an architecture suffix, following
cedar-detect. The model file needs a decision: ship it in git (75MB for `tiny.en`, 40MB for
Vosk small) or download on first use, which needs network and therefore fails in the field.
Both the Raspberry Pi OS image and NixOS need it. Unknown effort until WP2 picks the engine.

**WP6. Docs.** A CONTEXT.md for the new context, the ADR on audio-as-artifact, the ADR on
deferred transcription (possibly the same one), a user guide section, and the privacy line.

---

## 7. Risks and kill criteria

If WP2 shows transcription costing more than roughly twice the audio duration with the
solver running, or measurably dropping the solve rate, kill on-device recognition. WP1
alone already gives you downloadable recordings, so "record now, transcribe on a laptop"
remains a complete feature, just a less magical one.

If designations come back mangled often enough that every transcript needs hand-editing,
the honest framing is "audio memos with a rough searchable index", not "voice notes", and
WP4 stops being optional.

If sustained inference costs meaningful battery runtime on a rev4, gate it behind a setting
and default it off.

---

## 8. What I would actually build

WP0 and WP1. Free-text notes plus voice memos. No new binaries, no model files, no CPU
risk, no accuracy problem, and it is a coherent feature that people would use. Everything
about transcription sits on top of that and can be decided later, on evidence from WP2,
without any of it being wasted work.

---

## Sources for the performance claims

- [whisper.cpp discussion #166, "Real-time transcription on Raspberry Pi 4"](https://github.com/ggml-org/whisper.cpp/discussions/166)
- [vosk-api on GitHub](https://github.com/alphacep/vosk-api)
- [Interpreting speech with a Raspberry Pi, Dr John's Tech Talk](https://drjohnstechtalk.com/blog/2022/11/interpreting-speech-with-a-raspberry-pi/)

Treat all of them as indicative only. The number that matters is the one measured on a
PiFinder with the solver running.
