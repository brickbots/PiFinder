# Bring-up

The Bring-up context covers the first power-on validation of a freshly assembled PiFinder board: a builder runs one command, the board exercises its own screen, keypad backlight, buzzer, IMU, charger and every switch, and reports what it could verify. It is **bench tooling, not a runtime slice** — nothing in the running application depends on it, and it deliberately does not boot the application (no catalogs, no solver, no shared state). Cross-cutting, like the NixOS context.

## Language

### The run

**Bring-up**:
The first power-on validation of a newly assembled board, done at the bench before the unit is configured, imaged for a customer, or used to observe. Distinct from field diagnostics (a working unit misbehaving) and from troubleshooting (a fault already suspected).
_Avoid_: "smoke test" (that names a pytest marker in this repo), "QA", "burn-in" (that's a soak, which this is not).

**Bring-up run**:
One execution of `python -m PiFinder.bringup` against one board. A run is interactive and open-ended: it keeps reporting until the builder ends it — with Ctrl-C, with `--timeout`, or with the **power hold**.
_Avoid_: "test run", "session".

**Power hold**:
The power switch held closed for one second, which ends the run and asks the OS for a clean shutdown. It exists because bring-up happens at a bench with no keyboard and often no terminal in sight, and pulling power on a mounted filesystem is how a builder corrupts an image between the first board and the tenth. The threshold matches the one `keyboard_pi` uses for the same switch in the running application, so the gesture is learned once. Distinct from a **tap**, which is all the `SWITCHES` check needs: bring-up is the one place where how *long* the power switch is closed changes what happens. Removed by `--no-power-shutdown`; a tap still counts either way.
_Avoid_: "power off" / "kill" (the run asks the OS to shut down and never drives the **power-off latch** itself — that stays the kernel's, see [Battery](../battery/CONTEXT.md)), "long press" (that names the UI context's `LNG_*` keys, which the power switch does not produce).

**Builder**:
The person assembling and validating the board — the audience for a bring-up run. Distinct from the **observer**, the person using a finished PiFinder at the eyepiece, who is the audience for everything in the [UI](../ui/CONTEXT.md) context.
_Avoid_: "user" (ambiguous — reserve it for the observer), "operator", "tester".

### Checks

**Check**:
One named hardware item a bring-up run reports on — `SCREEN`, `BACKLIGHT`, `BUZZER`, `IMU`, `CHARGER`, `SWITCHES`. Every check is exactly one of the three kinds below, and the kind determines whether it can count toward the **verdict**.
_Avoid_: "test" (collides with pytest), "assertion", "step" (checks are concurrent, not sequential).

**Probed check**:
A check whose answer the program obtains entirely on its own, by talking to the part — reading the IMU's chip-identity register, reading the charger's part-number register. Needs no builder and cannot be faked by a hopeful human.
_Avoid_: "automatic test", "self-test".

**Exercised check**:
A check the **builder drives** and the **program verifies**: the builder closes each switch and the program sees the closure. Human-initiated but machine-confirmed — which is why it can gate the verdict alongside probed checks.
_Avoid_: "interactive test", "manual check" (it is not manually *judged*).

**Witnessed check**:
A check where the program can only *emit* and the **builder is the sensor** — it drives the panel, the backlight and the buzzer, and only a human eye or ear can confirm the result. A witnessed check has no machine-readable outcome and therefore **never** contributes to the verdict; the run reports what it emitted, not whether it worked.
_Avoid_: "visual test" (the buzzer is audible), "passive check" (the program is actively driving hardware), claiming a witnessed check "passed".

**Pre-flight**:
A check on the **card's provisioning** rather than the board's hardware — kernel overlays, bus enablement, anything the OS image has to have set up before a part can answer. Run before the hardware checks and reported separately, because a failed pre-flight *invalidates* the checks that depend on it: a PWM channel that is exported but muxed to no pin makes a perfectly good buzzer silent. Naming it separately is what stops a misprovisioned image from being diagnosed as a bad board.
_Avoid_: folding it into a probed check (a probed check interrogates the *board*), "environment check".

**Verdict**:
A bring-up run's overall result, computed over its **probed** and **exercised** checks only, and surfaced both on the panel and as the process exit status. Silent about everything witnessed.
_Avoid_: "result" (vague), "score", implying a verdict covers the screen or buzzer.

### The keypad, physically

**Switch**:
One physical pushbutton on the board, identified by where it sits in the wiring — the unit bring-up validates, because a switch is a solder joint that can be cold, bridged or missing. Distinct from a **key**, the [UI](../ui/CONTEXT.md) context's logical keycode: two switches can send the same key, so proving "the UI received UP" does **not** prove which switch closed.
_Avoid_: "button" (fine in prose to a builder, too loose in code), "key" (that's the logical event).

**Matrix position**:
A switch's `(row, column)` coordinate in the scanned keypad matrix — a switch's identity for bring-up purposes. The **power switch** is the exception: it is wired to its own line rather than into the matrix, and so has no matrix position. It is also the only switch whose *duration* means anything (see **power hold**); every matrix position is judged purely on whether it was observed closing.
_Avoid_: "keycode" (that's the logical key), "index".

**Population map**:
Which matrix positions actually carry a switch on a given board revision. The matrix is scanned identically on every revision, but revisions populate different subsets: rev3 carries a bottom-row directional cluster (17 switches), rev4 carries a right-hand column instead, with its own centre `SQUARE` (18 switches). A bring-up run counts closures against the population map for the revision it is validating — an unpopulated position is not a failure.
_Avoid_: "keymap" (that maps positions to logical **keys**, a different table), "layout".

## Flagged ambiguities

- **"test"** — heavily overloaded here. In this repo it already means a pytest case (`pytest -m smoke`). A bring-up run is not a pytest run and is never invoked by the test suite; say **check** for one item and **bring-up run** for the whole thing. This is why the entry point is `PiFinder.bringup` and not `PiFinder.hw_test`.
- **"detected"** — `hardware_detect` probes the I²C bus to *decide how the application configures itself* (which panel, which processes spawn). A bring-up **probed check** asks the same bus a similar question but treats the answer as a **finding to report**, never as a configuration input. A board whose charger is dead must still bring its screen up, so bring-up never lets a probe result pick its panel.
- **"passed"** applied to a witnessed check — meaningless. The program drove the buzzer; whether sound came out is not something it can know. Report witnessed checks as *emitted*, and let the verdict stay silent on them.
- **switch vs key** — the [UI](../ui/CONTEXT.md) glossary is written in **keys** (`UP`, `ALT_PLUS`, `LNG_SQUARE`), which is right for that context: the UI cares what the observer meant. Bring-up is written in **switches** and **matrix positions**, because it cares which joint conducts. Don't mix the vocabularies in one sentence.
- **unpopulated vs faulty** — a matrix position that never closes is a *fault* only if the **population map** says a switch is there. On rev4 most of the rev3 bottom row is silent by design.
- **misprovisioned vs faulty** — the most expensive confusion bring-up exists to prevent. A silent buzzer, a black panel and an absent IMU all have two candidate causes: the *board* (a bad joint, a wrong part) and the *card* (a missing overlay, a disabled bus). The first is fixed with an iron, the second with a text editor, and a builder who reaches for the iron first will desolder a good part. Every check that depends on provisioning gets a **pre-flight** so the two are never reported as one thing.

## Example dialogue

> **Dev:** The run says `SWITCHES 17/18`. Which button is broken?
>
> **Domain:** Whichever matrix position is still unlit on the grid — that's the point of showing positions rather than key names. If it said "UP is missing" you'd have to guess between two switches, since more than one position can send `UP`.
>
> **Dev:** Most of the bottom row never lights up. Dead switches?
>
> **Domain:** No — those aren't in rev4's population map. rev3 put the directional cluster along the bottom; rev4 moved it to the right-hand column, so on rev4 only that row's last position is populated. Same scan, different populated subset, and an unpopulated position is not a fault.
>
> **Dev:** So can I let the verdict include the screen? The panel obviously works, I'm reading the verdict *on* it.
>
> **Domain:** The screen is a witnessed check — you're the sensor, not the program. It can tell you it drew the patterns; it can't tell you a corner column is dead or the panel is the wrong part. Only probed and exercised checks feed the verdict, so a green verdict means "the IMU and charger answered and every populated switch closed", nothing more.
>
> **Dev:** The charger didn't answer on this board. Should the run bail out?
>
> **Domain:** No. It reports `CHARGER` as failed and carries on with everything else — you still want to know whether the switches and the IMU are good before you desolder anything. And it must never let that probe decide which panel to open, or a dead charger would look like a dead screen.
>
> **Dev:** I pressed power to tick off the last switch and the thing shut down on me.
>
> **Domain:** You held it. A tap is what the `SWITCHES` check wants — the closure registers on the first scan that sees it — and a second's hold is the **power hold**, which ends the run and shuts the card down cleanly. The power cell fills a bar for that whole second so you can let go; if you'd rather not have the gesture at all, `--no-power-shutdown` takes it away and the tap still counts.
>
> **Dev:** Why does bring-up get to shut the machine down when nothing else in it touches power?
>
> **Domain:** It asks the OS to shut down — the same `shutdown now` the app's menu ends up running. It still doesn't touch the **power-off latch**; GPIO14 is the kernel's to drive at power-off and no Python here or anywhere else goes near it. What bring-up avoids is a builder at a bench with no terminal open reaching for the barrel jack on a mounted filesystem.
