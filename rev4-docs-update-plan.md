# rev4 Documentation Update — Plan & Agent Handoff

**Status:** plan only, no docs changed yet.
**Scope:** `docs/source/*.rst` (the published Sphinx site at pifinder.readthedocs.io) — bringing the
user-facing manual in line with rev4 hardware now that v2.6.1 ships full software support for it.
**Written:** 2026-08-06, against `origin/main` @ `4a83d25b`.

Everything below is sourced from the repo. Where a fact is *not* in the repo it is called out under
"Open questions" rather than guessed — agents must not invent hardware facts.

---

## 1. What rev4 actually changed

Distilled from `release_notes/2.6.1.md`, `docs/ax/{battery,sound,bringup}/CONTEXT.md`,
`docs/adr/000{6,7,8}`, `docs/adr/0017`, `docs/adr/002{0,1,3}`,
`python/PiFinder/{keypad,displays,hardware_detect}.py`, `python/PiFinder/types/hardware.py`,
`CONTEXT-MAP.md`.

| Area | rev3 (what the docs describe today) | rev4 |
|---|---|---|
| **Power switch** | White **slide** switch on top | Momentary **power button** (LTC2954). Press → shutdown confirmation; second press confirms. Shutdown sound plays, then the kernel drives **GPIO14** low to trip the power latch (ADR 0007) |
| **Charging** | Optional **PiSugar S Plus** 5000 mAh add-on board, blue/green LED | **On-board BQ25895** charger, I²C `0x6A`. Software re-asserts a fast-charge config (~1.5 A in/fast, watchdog off, auto-adapter-detect off) every poll (ADR 0017) |
| **Battery UI** | *None* — docs explicitly say there is no indicator and no warning | Title-bar battery glyph in ~20% buckets plus a charging bolt (`ui/base.py:121-128`, `_battery_icon()` at `:345`). State of charge is **hidden while charging** and while ADC-blind |
| **Low battery** | Unit simply dies | Advisory popup + sound **once at 10%** and **once at 5%**; below the **ADC blind floor** (~3.5 V, four consecutive polls on battery) a final warning then an **orderly software shutdown** (ADR 0021). Warnings latch for the whole discharge; only plugging in re-arms them |
| **Sound** | None | Passive piezo buzzer, hardware PWM ch0 / GPIO12. Cues for startup, shutdown, keypress, error, low battery. New setting **Settings → User Pref → Volume** (Off, 1–5) |
| **Display** | 1.5" **SSD1351**, 128×128 | 1.91" **SSD1333**, **176×176**. Fonts run ~15–20% larger (`Layout176`, `displays.py:166`). Dimming range widened to 13,400:1 — dimmest step from 0.106% → **0.005%** of full (ADR 0023) |
| **Keypad** | 17 switches: calculator pad + a **directional row along the bottom** | 18 switches: the **directional cluster moved to the right-hand column (col 4)** and gained its **own centre SQUARE**. Two positions now send SQUARE (`keypad.py:96-112`) |
| **Build variants** | Left / Right / Straight / Flat v2 / Flat v3 | adds **AS Bloom, AS Heart, Rev4 Left, Rev4 Right, Rev4 Straight** — each carries its own IMU-to-camera constants |
| **Bring-up** | — | `python -m PiFinder.bringup` validates a fresh board: SCREEN, BACKLIGHT, BUZZER, IMU, CHARGER, SWITCHES, plus a card-provisioning **pre-flight**. Power-hold (1 s) ends the run with a clean shutdown |

**Naming canon** (`docs/ax/*`, product KB, and prior project decisions): the fourth hardware version
is **"revision 4" / "rev4"** — never "V4" or "v4". Legacy config values `v4_left/right/straight` are
aliased to `rev4_*` in `config.py:17-19`; do not surface the legacy spelling in docs.

---

## 2. Decisions to confirm before agents start

These fork the work. My recommendation is given first; all four are cheap to answer and expensive to
get wrong halfway through.

**D1 — How does the manual address two live revisions?**
*Recommend:* keep one doc set. Write rev4 as the **default** voice for shipping units and call out
rev3/v2.5 differences in `.. note::` blocks only where behaviour actually diverges (power, charging,
keypad geography, screen size). Add one short **"Which PiFinder do I have?"** section — identify by
screen size and keypad layout — and link to it from the version note on each page.
*Rejected:* a parallel rev4 doc set (doubles maintenance, splits Discord links); revision tabs
(`sphinx-tabs` is not a current dependency, see `docs/source/requirements.txt`).

**D2 — What do the docs *call* the revisions?**
The manual currently says "v3 and v2.5"; the code and domain docs say "rev3"/"rev4".
*Recommend:* introduce **"rev4"** in user-facing prose (matching canon and the board silkscreen) and
**do not retro-rename** v3/v2.5 — those names are on the website, on invoices and in years of
Discord history. The "Which PiFinder do I have?" table is where the two naming systems get
reconciled. Worth a `/grill-with-docs` pass if you want the terminology hardened before agents run.

**D3 — Do we reshoot the screenshots at 176 px?**
There are **118 screenshots at 256×256**, all derived from 128×128 captures. A rev4 owner's screen
looks noticeably different (bigger glyphs, more room).
*Recommend:* **staged.** Phase 1 reshoots only the screens that are *new or changed* on rev4
(battery icon, low-battery popups, power-button shutdown confirm, Volume menu, PiFinder Type). Phase
2 — a full 176 px reshoot of the whole manual — is a separate, mechanical, later job. Do not block
the rev4 content on it.

**D4 — Is the rev4 DIY build path in scope?**
The repo has **no rev4 case STLs** (`case/` holds v1, v2, v2.5, v3 only), **no tracked rev4
gerbers** (`gerbers/PiFinder_smt*.zip` are untracked at the repo root) and **no rev4 KiCad project**
(`kicad/` holds v2 and v3). `build_guide.rst` and `BOM.rst` describe a through-hole rev3 build in
868 + 137 lines and 133 images.
*Recommend:* **out of scope for this pass.** Add a single honest note to both pages saying they
cover the v3/v2.5 through-hole build and that rev4 build files are not yet published. Revisit when
the hardware artifacts land in the repo.

---

## 3. Current state of the docs

### Already rev4-aware (leave alone)
- `menu_map.rst:265` — PiFinder Type already lists AS Bloom, AS Heart, Rev4 Left/Right/Straight.
- `dev_guide.rst:589-608` — `-fh` (emulates rev3) and `-fb/--fakebattery` (emulates rev4) documented.

### Actively wrong on rev4 (highest priority — these mislead an owner)
| File | Lines | Problem |
|---|---|---|
| `user_guide.rst` | 773-776 | *"There is **no battery-level indicator** on the screen and no low-battery warning: when the charge is depleted the PiFinder simply shuts off."* — false on rev4 in all three claims |
| `user_guide.rst` | 819, 824-826, 838-841 | PiSugar S Plus board: "do not disassemble", "the PiSugar power board manages charging", "the only compatible part is the PiSugar S Plus 5000mAh". rev4 has no PiSugar |
| `user_guide.rst` | 723-742 | "The two USB-C ports" + charging-port LED + the keypad-side port being wired ahead of the switch + "the small white **slide** switch" |
| `user_guide.rst` | 763-771 | "four to five hours" runtime — a v3/PiSugar number |
| `quick_start.rst` | 48-68 | Same slide-switch / two-port / blue-green-LED story |
| `quick_start.rst` | 555-563 | Shutdown via hold-LEFT → Quick Menu → SHUTDOWN. On rev4 the power button is the natural gesture |
| `quick_start.rst` | 123-137 | Configuration Setup offers "Right/Left/Straight/Flat" — omits all five rev4 variants |
| `troubleshooting.rst` | 16-33 | "Power is a small white **slide switch**", "There's no battery-level indicator on screen", "double-check the PiSugar battery board connections" |
| `index.rst` / `quick_start.rst` / `troubleshooting.rst` | 11 / 5 / 4-7 | Version notes say "for v3 and v2.5 PiFinders" — rev4 is not named anywhere |
| `BOM.rst` | all | Waveshare 1.5" OLED, 17 switches, GT-U7, PiSugar — rev3 through-hole only |

### Missing entirely
- Battery indicator: what each glyph means; why no percentage appears while charging.
- Low-battery behaviour: the 10% / 5% advisories, and the automatic clean shutdown.
- Sound & the **Volume** setting — absent from **both** `user_guide.rst` and `menu_map.rst`
  (`menu_map.rst:206-224` lists User Pref without it). This is a shipped 2.6.1 setting with zero docs.
- The power button as an interaction (press → confirm → second press).
- The rev4 keypad geography — every key instruction still *works*, but the photos show a rev3 pad.
- The 176×176 screen: bigger panel, wider dimming range.
- Bring-up tool — builder-facing, no user-facing doc at all.
- What AS Bloom / AS Heart / Rev4 Left / Right / Straight actually *are*, and how an owner picks.

---

## 4. Work packages

Six packages. WP0 first (it unblocks screenshots); WP1–WP4 then run in parallel; WP5 last.
Each is sized for one agent. Every agent should invoke the **`docs` skill** first — it carries the
house voice, the rST conventions, the page charters and the screenshot pipeline.

---

### WP0 — Unblock 176 px screenshot capture *(do first; small, code-only)*

**Problem:** `.claude/skills/pifinder-remote/scripts/pf_remote.py:279` hardcodes
`--display headless`, which is 128×128. `displays.py` already has `DisplayHeadless176`
(selector `headless_176`, `displays.py:535-557`), so the panel is one flag away.

**Tasks**
1. Add a `--display` passthrough to `pf_remote.py launch` (default unchanged at `headless`), so an
   agent can run `python3 $S launch --display headless_176`.
2. Confirm `GET /api/screen` returns the 176×176 frame under that driver.
3. `screenshot_to_doc.py` needs no change — `--scale 2` turns 176 → 352. Note in the skill that rev4
   doc images are 352×352 where rev3's are 256×256.
4. Update `.claude/skills/pifinder-remote/SKILL.md` (lines 5-6, 37, 52-53, 167), which currently
   states 128×128 as a flat fact.
5. Update `.claude/skills/docs/SKILL.md` "Preparing screenshots" (lines 227-270) with the rev4 path.

**Also fix here:** `.claude/skills/docs/references/product-knowledge-base.md:24` still describes rev4
as *"Planned future revision… still in early design: engineering samples of potential screens exist
but no working prototype on a scope yet."* Any agent trusting that reference will write nonsense.
Rewrite that entry from `release_notes/2.6.1.md` and the table in §1 above.

**Acceptance:** an agent can capture a rev4 screen end-to-end and land a 352×352 amber PNG in
`docs/source/images/`.

---

### WP1 — Power & Charging rewrite *(largest; highest user impact)*

**Files:** `user_guide.rst` (713-842), `quick_start.rst` (48-68, 555-563), `troubleshooting.rst` (16-33)

Per ADR 0015, Power & Charging **stays in `user_guide.rst`** (it fails separability — it is core to
operating the device and must survive the "printable user guide" test). Do not spin out a new page.

**Tasks**
1. Restructure the section so rev4 is the primary narrative and v3/PiSugar facts move into clearly
   scoped notes. Sub-sections to end up with, roughly: *Power button and shutdown* · *Charging* ·
   *The battery indicator* · *Low-battery warnings and automatic shutdown* · *Battery life* ·
   *Running on external power* · *Battery safety & care*.
2. **Delete the false claims** at `user_guide.rst:773-776` and the PiSugar-as-universal-truth framing
   at 819-841. Keep the PiSugar material, scoped to v3 units.
3. Document the battery indicator honestly, using the Battery glossary's vocabulary:
   - The glyph is a **state-of-charge estimate**, expressed as *remaining runtime under typical
     load*, not "% of capacity left" (ADR 0020). Say "how much longer it will run".
   - **No percentage is shown while charging** — the charger pulls terminal voltage up, so a number
     would lie. The bolt glyph appears instead.
   - Near the end of a discharge the charger's ADC goes blind and the icon shows empty.
   - Never write "battery level" (bare) — the glossary flags it as ambiguous.
4. Document low-battery behaviour: an advisory at 10% and again at 5% with a sound, each **once per
   discharge**; then a final warning and an **orderly shutdown** that exists specifically to avoid an
   SD-corrupting hard cut. Say plainly that plugging in re-arms the warnings.
5. Document the power button: press opens a shutdown confirmation, a second press confirms, a tone
   plays and the unit powers itself off. Cross-link `user_guide:shutdown`.
6. Rewrite `quick_start.rst` "Powering the PiFinder" and "Shutting down the PiFinder" to match.
7. Fix `troubleshooting.rst` "The PiFinder won't turn on": power button not slide switch; the
   battery indicator now exists; PiSugar advice scoped to v3 builds.

**Facts you may NOT state** (see Open questions): rev4 battery capacity, rev4 runtime in hours,
charge time, how many USB-C ports rev4 has, or whether rev4 has a charge-indicator LED. Leave a
clearly-marked `TODO(rich)` where a number is needed.

---

### WP2 — Sound, Volume, and the Settings/Menu Map gap

**Files:** `user_guide.rst` (Settings Menu, 843-866), `menu_map.rst` (User Pref block, 206-224)

**Tasks**
1. Add **Volume** to `menu_map.rst` under User Pref, in the existing definition-list style, adjacent
   to Key Bright. Values: Off, 1–5.
2. Add a short Settings-menu paragraph in `user_guide.rst` on what the sounds are for: short cues on
   keypress, startup, shutdown, errors and low battery. Note the setting only appears on hardware
   that has the buzzer.
3. Vocabulary: the Sound glossary calls these **earcons**, but that is a domain term — in
   user-facing prose write "sounds" or "tones" and keep "earcon" out of the manual.
4. Honest caveat worth one sentence: the piezo is loudest near its resonant peak, so the cues differ
   in loudness by design — that is not a fault.

**Acceptance:** a rev4 owner who hears a beep can find out what it was and how to turn it off.

---

### WP3 — Screen, keypad, and "Which PiFinder do I have?"

**Files:** `user_guide.rst` (How It Works / The Menu System, 20-70), `quick_start.rst`
(Unboxing 31-46, Using the PiFinder 72-121, Configuration Setup 123-137), `index.rst` (11)

**Tasks**
1. Write the **"Which PiFinder do I have?"** section (D1/D2). Identify by the two things an owner can
   see without opening anything: **screen size** (1.5" 128×128 vs 1.91" 176×176) and **keypad
   layout** (directional keys along the bottom vs a directional cluster down the right-hand side).
   Put it in `quick_start.rst` near Unboxing and `:ref:` to it from the version notes.
2. Update the version notes on `index.rst:11`, `quick_start.rst:5`, `troubleshooting.rst:4-7` to name
   rev4.
3. Extend **Configuration Setup** (`quick_start.rst:123-137`) to cover all the PiFinder Type options
   including the five rev4 entries, and say how to pick — which is a *physical* question about how
   the camera is oriented relative to the screen. `menu_map.rst:265` already lists them; keep the two
   consistent.
4. Note the wider brightness range on rev4 in the brightness passages
   (`quick_start.rst:227-239`): the dimmest setting goes far lower than on the 128 px panel, which
   matters at a dark site. Do not quote the raw 0.005% / 13,400:1 engineering figures in the manual —
   say it goes "much dimmer" and leave the numbers to ADR 0023.
5. The key-name list at `quick_start.rst:83-95` is duplicated in `user_guide.rst` (there is a comment
   marking it) — if you touch one, touch both.

**Do not** rewrite every key instruction. The logical keys are unchanged; only the photos and the
"where is it on the pad" framing need attention.

---

### WP4 — Bring-up: a builder-facing page

**New file:** `docs/source/bringup.rst`, registered in the `index.rst` "Building & upgrading"
toctree, after `build_guide`.

This passes ADR 0015's test: readers arrive at it directly ("I built a board, does it work?") and it
is fully separable from the operate-and-observe storyline.

**Source of truth:** `docs/ax/bringup/CONTEXT.md` (read it in full — the vocabulary is deliberate)
and `python/PiFinder/bringup.py`.

**Tasks**
1. Cover: what a bring-up run is and when to do it; the one command; the six checks; the pre-flight;
   the switch grid and how to read it; the power hold; `--no-power-shutdown` and `--timeout`.
2. Get the **check kinds** right — this is the whole point of the tool:
   - **Probed** (IMU, charger): the program asked the part directly.
   - **Exercised** (switches): you press, the program confirms.
   - **Witnessed** (screen, backlight, buzzer): the program can only *emit*; you are the sensor.
     Never say a witnessed check "passed" — the verdict is silent about them.
3. Say clearly that an unpopulated matrix position is **not** a fault: rev3 populates the bottom row,
   rev4 populates the right-hand column. This is the single most likely misread.
4. Say clearly that a **pre-flight** failure means the *card*, not the board — a builder who reaches
   for the soldering iron on a provisioning fault will desolder a good part.
5. Voice: the audience here is a **builder** at a bench, not the observer at the eyepiece. Stay in
   the manual's voice but assume a soldering iron is nearby.
6. Avoid the word "test" for a bring-up run — it collides with pytest throughout this project.

---

### WP5 — Build Guide & BOM: honest scoping *(small, do after D4 is confirmed)*

**Files:** `build_guide.rst` (7-16), `BOM.rst` (1-8)

Assuming D4 lands as recommended: add a short note at the top of each page stating that it covers the
v3 / v2.5 through-hole build, and that rev4 build files are not yet published. Do not attempt a rev4
BOM — the parts are not in the repo.

If D4 flips to "in scope", this becomes the largest package in the plan and needs its own handoff.

---

## 5. Ordering

```
WP0 (tooling)  ──┬──> WP1 (power)        ─┐
                 ├──> WP2 (sound)         ├──> WP5 (build/BOM notes) ──> final Sphinx build check
                 ├──> WP3 (screen/keypad) ┤
                 └──> WP4 (bring-up)      ─┘
```

WP1–WP4 touch mostly disjoint sections, but **WP1 and WP3 both edit `quick_start.rst`** and **WP1,
WP2, WP3 all edit `user_guide.rst`**. Either run them sequentially, or give each agent its own
worktree and merge — do not run them concurrently in a shared checkout.

**Every agent finishes with:**
```bash
cd docs && sphinx-build -b html -n source /tmp/pifinder_docs_build 2>&1 | grep -iE "warning|error"
```

**Baseline verified 2026-08-06: the docs build clean — zero warnings in nitpicky mode.** So any
warning you see is one you introduced. Resolve it — especially "undefined label" (a mistyped
`:ref:`) and "toctree contains reference to nonexisting document".

**Environment gotcha:** the project venv (`python/.venv`) has Sphinx 6.2.1 and **no
`sphinxcontrib-mermaid`**, so `sphinx-build` fails there with
`Could not import extension sphinxcontrib.mermaid`. `menu_map.rst` is full of mermaid diagrams, so
this is not skippable. Build in a throwaway venv instead:
```bash
python3 -m venv /tmp/docsvenv
/tmp/docsvenv/bin/pip install -r docs/source/requirements.txt   # Sphinx 7.2.6, rtd-theme, mermaid
cd docs && /tmp/docsvenv/bin/sphinx-build -b html -n source /tmp/pifinder_docs_build
```
Do not "fix" this by installing into the project venv — the docs pins differ from the app's.

---

## 6. Photos needed (physical rev4 hardware — Rich must shoot these)

Agents cannot produce any of these. Where an existing image is superseded, the current file is named
so the replacement can be dropped in and the `.. image::` directive updated.

### Blocking — WP1 cannot be finished without these
| # | Photo | Target | Replaces / joins |
|---|---|---|---|
| 1 | **rev4 top-down: power button + USB-C port(s)**, with callout arrows/boxes in the style of the current shot | `quick_start.rst:58`, `user_guide.rst:728` | `images/quick_start/power.jpeg` — *the single most wrong image in the manual; it shows a slide switch* |
| 2 | **rev4 charging** — cable in, showing whatever charge indication rev4 has (LED? on-screen only?) | `user_guide.rst` Charging | new |
| 3 | **rev4 side/port view** — how many USB-C ports and which is which | `user_guide.rst` Charging | supports or replaces "The two USB-C ports" |

### Blocking — WP3
| # | Photo | Target | Replaces / joins |
|---|---|---|---|
| 4 | **rev4 front, straight on** — 1.91" panel + right-hand directional cluster clearly visible | `quick_start.rst:38` | joins `images/quick_start/pf_front.jpeg` |
| 5 | **rev4 rear** | `quick_start.rst:40` | joins `images/quick_start/pf_rear.jpeg` |
| 6 | **rev4 keypad close-up, annotated** — directional cluster, its centre SQUARE, number pad, +/-, SQUARE on the pad | new "Using the PiFinder" / keypad passage | new — the key geography moved |
| 7 | **rev3 next to rev4, screens lit, same frame** — the size difference is the fastest way to answer "which do I have?" | "Which PiFinder do I have?" | new |

### Blocking — Configuration Setup (WP3)
| # | Photo | Target | Notes |
|---|---|---|---|
| 8 | **Rev4 Left / Rev4 Right / Rev4 Straight** — one frame if they read clearly together, else three | `quick_start.rst:126-137` | joins `images/quick_start/v3_slate_family_front.jpeg` |
| 9 | **AS Bloom** unit | Configuration Setup | these are menu options an owner must self-identify; there is currently no picture of either |
| 10 | **AS Heart** unit | Configuration Setup | as above |

### Non-blocking but wanted
| # | Photo | Target | Notes |
|---|---|---|---|
| 11 | rev4 mounted on a scope | `quick_start.rst:151` | joins `images/quick_start/pifinder_mounted.jpeg` |
| 12 | rev4 banner / hero shot | `index.rst:7` | joins `images/PiFinder_v3_banner.png` |
| 13 | rev4 case opened for SD-card access, per configuration | `sd_card.rst:50-72` | only if the rev4 case differs from v3 — **confirm before shooting** |
| 14 | rev4 battery in place / battery compartment | `user_guide.rst` Battery safety & care | supports the safety section |

### WP4 (bring-up) — probably photos, possibly screenshots
| # | Photo | Notes |
|---|---|---|
| 15 | rev4 panel mid-bring-up: switch grid with some positions lit | `bringup.py` accepts `--display headless_176`, so a *rendered* frame may be capturable on a dev box — but the checks need real hardware to show a realistic state. **Try headless first; fall back to photographing the bench.** |
| 16 | rev4 panel showing the power-hold progress bar | as above |
| 17 | rev4 board bare, top side, buzzer and charger locatable | only if D4 puts the DIY build in scope |

**Shooting notes:** match the existing manual's style — plain background, even light, unit filling
the frame, callouts drawn as the current `power.jpeg` does. Landscape where the existing image is
landscape so `:width: 45%` side-by-side pairs still line up.

---

## 7. Screenshots (agents can produce these — after WP0)

Capture at 176×176 via `pf_remote` with `--display headless_176`, then
`screenshot_to_doc.py --scale 2` → 352×352. `-fb/--fakebattery` runs a full simulated discharge lap,
so every battery state below is reachable without hardware.

- Title bar at each battery bucket: full, 80, 60, 40, 20, empty — plus the charging bolt.
- "Low battery at 10%" popup; "Low battery at 5%" popup.
- Shutdown confirmation as reached by the power button.
- Settings → User Pref → **Volume** menu.
- Settings → Advanced → **PiFinder Type**, showing the five rev4 entries
  (replaces `images/quick_start/pifinder_type_select.png`).
- Status screen at 176 px.
- Main menu at 176 px (for "Which PiFinder do I have?" alongside the 128 px original).

Deferred to the D3 phase-2 job: the remaining ~111 of the 118 existing 256×256 screenshots.

---

## 8. Open questions — facts not in the repo

Agents must **not** guess these. Leave `TODO(rich)` markers and flag them in the summary.

1. **Battery capacity and runtime.** ADR 0020 says the `SOC_LUT` is still generic Li-ion folklore
   pending the measured bench campaign, so **no rev4 runtime figure is publishable yet**. The
   existing "four to five hours" is a v3/PiSugar number and must not be carried over.
2. **Charge time** from empty on rev4.
3. **How many USB-C ports** rev4 has, and whether the "one charges, one is wired ahead of the switch"
   split still holds.
4. **Charge-indicator LED** — does rev4 have one? The BQ25895 has a `/STAT` pin but nothing in the
   repo says whether it drives a visible LED.
5. **Is rev4 sold assembled only?** Drives D4 and whether a rev4 BOM is ever written.
6. **Does the rev4 case differ** enough to need new SD-card-swap photos and printed-parts coverage?
7. **What "AS" means** in AS Bloom / AS Heart, and whether those names are customer-facing.
8. **GPS receiver on rev4** — `BOM.rst:58` lists the GT-U7. `menu_map.rst:276` mentions a UBlox-10
   baud option, and the 2.6.1 GPS work touched M8/M9/M10 parsing. If the rev4 receiver changed, both
   pages need it.
9. **Does rev4 still take the same camera modules** (imx296 / imx462)?

---

## 9. Guardrails for every agent

- Edit **`docs/source/*.rst` only**. `docs/*.md` are four-line redirect stubs — editing them is the
  classic trap. Do not touch `docs/ax/*/CONTEXT.md` or `docs/adr/*` (that is `grill-with-docs`
  territory).
- **Read the section you are about to change, and its neighbours, before writing.** The manual has a
  settled voice; your edits should disappear into it.
- Say **"rev4"**, never "v4" or "V4".
- Never write bare **"battery level"** — say battery voltage (measured) or state of charge
  (estimated). Never describe the percentage as capacity remaining.
- Never claim a **witnessed** bring-up check "passed".
- Never invent an image filename. If a photo from §6 does not exist yet, reference a clearly-named
  placeholder path and flag it in your summary.
- Finish with the nitpicky Sphinx build and report the result.
