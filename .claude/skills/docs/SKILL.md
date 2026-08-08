---
name: docs
description: >-
  Author and edit PiFinder's user-facing documentation in the project's house
  style. The published docs are reStructuredText (.rst) in docs/source/, built
  with Sphinx + the Read the Docs theme and hosted at pifinder.readthedocs.io.
  Use this skill whenever the user wants to write, add, update, or polish
  documentation — documenting a new feature, menu, screen, or setting in the
  user guide; creating a new doc page and wiring it into the toctree; or
  revising existing prose for clarity and voice — even if they never say
  "reStructuredText" or "Sphinx". Trigger on mentions of docs, documentation,
  user guide, quick start, build guide, readthedocs, .rst files, or
  "document this feature / write up how this works". Do NOT use for docs/ax
  CONTEXT.md glossaries or ADRs (use grill-with-docs for those), for Python
  docstrings / code comments, or for edits confined to the repo-root README.
---

# Writing PiFinder Documentation

PiFinder's published documentation is a Sphinx site written in **reStructuredText**.
Your job with this skill is to add or improve pages that a reader moves through
without friction: the same rST conventions, the same cross-reference style, and
the plain, consistent prose described under **The house voice** below. That
voice is the part most likely to slip, so read it before you write.

## Orient first (and avoid the big trap)

The real documentation lives in **`docs/source/*.rst`**. It is built by Sphinx
and published to `pifinder.readthedocs.io`.

The trap: `docs/*.md` (e.g. `docs/user_guide.md`) are **four-line redirect
stubs** pointing at Read the Docs. They are not the docs. If you find yourself
editing a `.md` file under `docs/`, stop — you're in the wrong place. Edit the
matching `docs/source/<name>.rst`.

The page set (registered in `docs/source/index.rst`):

| File | Covers |
|------|--------|
| `quick_start.rst` | First-night, get-observing walkthrough |
| `user_guide.rst` | Workflow reference for operating & observing — the printable core; defers enumeration to `menu_map`, deep topics to satellite pages |
| `menu_map.rst` | Every menu item in the tree, one entry each |
| `equipment.rst` | Telescopes & eyepieces: gear setup, magnification/TFOV, flip/flop |
| `catalogs.rst` | Object catalogs included |
| `connectivity.rst` | Reaching the device from another device: WiFi modes, web interface, SMB share |
| `skysafari.rst` | SkySafari / planetarium integration |
| `troubleshooting.rst` | Symptom-led fixes and FAQ |
| `build_guide.rst` | Assembling the hardware |
| `v25_upgrade.rst` | Upgrading a v2 unit |
| `software.rst` | Flashing / updating the software image |
| `sd_card.rst` | Swapping / re-imaging the SD card |
| `dev_guide.rst`, `dev_arch.rst` | Contributor / architecture docs |
| `api.rst` | HTTP API reference |
| `BOM.rst` | Bill of materials |

## Two hardware revisions are live

The manual covers **rev4**, **v3** and **v2.5** PiFinders. rev4 is the current hardware, fully
enabled in software from v2.6.1, and it differs from v3 in ways a reader will hit immediately:

| | v3 / v2.5 | rev4 |
|---|---|---|
| Power | white **slide switch** | **power button** — press, confirm, second press shuts down |
| Charging | optional **PiSugar S Plus** add-on | on-board charger; **battery icon in the title bar**, warnings at 10% and 5%, automatic clean shutdown when flat |
| Directional keys | four separate arrow buttons along the bottom | a single **5-way joystick**; pressing it in acts as **SQUARE** |
| Screen | 1.5", 128×128 | 1.91", **176×176**, larger glyphs, much wider dimming range |
| Sound | none | buzzer with a **Volume** setting (Off, 1–5) under User Pref |

Three rules for writing across both:

1. **Write rev4 as the default case.** Plain prose describes rev4; v3/v2.5 differences go in a
   `.. note::` under the passage they affect — not the other way round, and not balanced
   "on rev4… on v3…" pairs in every paragraph.
2. **Call it "rev4"** — never "v4" or "V4". Leave **v3** and **v2.5** named as they are; those names
   are on the website, on invoices and throughout Discord. Do not retro-rename them to rev3/rev2.5.
3. **Logical key names are identical on both.** "Press **RIGHT**", "hold **SQUARE** and press **+**"
   are correct everywhere. Explain the joystick once, early, and then trust the reader — don't append
   "(or push the joystick right)" throughout.

```rst
Press the power button on top to start the PiFinder.  To shut down, press it again — the
screen asks you to confirm, and a second press powers the unit off.

.. note::
   On v3 and v2.5 PiFinders, power is a white slide switch rather than a button, and you
   shut down from the Quick Menu instead.
```

`build_guide.rst` and `BOM.rst` describe the v3/v2.5 through-hole build only. rev4 build files are
not published, so **do not add rev4 content or scoping notes to those two pages.**

**Section in `user_guide` vs standalone page** — a topic earns its own page only
when readers *arrive at it directly* with a task in hand (search, a Discord
answer, a cross-page link) **and** it is *separable* from the guide's
operate-and-observe storyline (a sentence + link suffices in its place).
Otherwise it's a `user_guide` section. Standalone page URLs get linked from the
wild — don't merge or rename pages casually. Rationale and worked examples:
`docs/adr/0015-user-docs-page-granularity.md`.

**Before writing a single line, read the page you're about to touch (or the
closest sibling).** Mirror its *structure*: heading depth, how it introduces
images, how it refers to other pages, how long its sections run.

Do not mirror its *sentence style*. Most of the manual was written before the
house voice below was settled, so the neighbouring paragraphs are a worked
example of layout and a poor guide to prose. Take the structure from the page
and the sentences from the rules.

## Get the facts right

Documentation that's confidently wrong is worse than none. Two bundled
references hold hard-won, authoritative product knowledge — **consult them
before writing about anything you're not certain of**, and prefer their facts
over your own assumptions about how the hardware behaves.

- **`references/product-knowledge-base.md`** — the big one. Distilled from real
  support threads, it covers product versions/configs, setup & first use
  (power/charging, GPS lock, focus, brightness, sleep mode), common issues,
  connectivity, catalogs, warranty, an FAQ, and a troubleshooting decision tree.
  It's long, so jump to the relevant `##` section rather than reading top to
  bottom. Especially useful for the troubleshooting/setup material that the user
  guide and quick start cover.
- **`references/hardware-support.md`** — diagnosis and troubleshooting detail
  (plate-solving focus/exposure, alignment, power, GPS interference, build
  issues).

Crucial framing: both files were written to guide **customer-support emails**,
not docs. Mine them for *facts* — specs, defaults, behaviors, the steps that
actually fix a problem — but never carry over their support voice (reassurance
scripts, escalation advice, sign-offs). Rewrite every fact in the manual's own
voice. If anything there conflicts with the code or the existing docs, trust the
code/docs and flag the conflict to the user rather than documenting the
discrepancy.

## The house voice

The manual follows a **simplified technical English** style. Write short, plain
sentences. Use the same word for the same thing every time.

This matters more here than in most software documentation. The reader is
usually outdoors in the dark. They are cold, their night vision is fragile, and
they are often reading on a phone one-handed. PiFinder's own interface ships in
German, Spanish, French and Chinese, so a large share of readers work through the
English manual as a second language. Short, predictable sentences survive those
conditions. Elegant long ones do not.

Simplified does not mean cold. The warmth comes from the words you choose and
from talking to the reader directly. It does not come from long sentences or
decorative punctuation. Keep the warmth. Shorten the sentences.

### The seven rules

1. **One idea per sentence.** Do not join two sentences with an em-dash or a
   semicolon. Use a full stop.
2. **Use active voice.** Name the actor. Use the passive only when the actor is
   genuinely unknown or does not matter.
3. **Start instructions with a command verb.** "Select Focus." A short condition
   or location may come first: "From the main menu, select Settings." Do not bury
   the verb behind a clause.
4. **Use simple tenses.** Simple present carries almost everything in a manual.
5. **Avoid auxiliary chains.** Write "you see", not "you will be able to see".
   Plain "can" and "may" are fine.
6. **Stack at most three nouns.** Hyphenate the modifier or add a preposition
   when a string grows: "the exposure time setting for the camera", not "camera
   exposure time setting".
7. **Use one word per concept.** See the table below.

Rule 7 is the one that decays fastest, because every writer reaches for a
synonym to avoid repetition. Repetition is correct here. These are the terms
that drift most in the current manual:

| Concept | Use | Not |
|---|---|---|
| Operate a key | **press** | push, tap, hit, click |
| Long-press one key | **press and hold** | hold, long-press |
| Choose a menu entry | **select** | choose, pick, activate |
| The physical screen | **the screen** | the display, the panel |
| The product | **the PiFinder** | the unit, the device, your device |
| Move within a menu | **scroll** | navigate, browse, go to |
| Power on / off | **turn on** / **turn off** | boot, power up, switch on/off |
| A catalog object | **object** | target, DSO |
| The user's telescope | **telescope** | scope, OTA, tube |
| Go up one menu level | **go back** | return, exit, back out |

The full table, the reasoning behind each choice, worked before/after examples,
and patterns for replacing em-dashes live in **`references/ste-style.md`**. Read
it before writing or revising more than a paragraph.

**Apply this to text you write, not to text you pass by.** The manual predates
this style and still contains 259 em-dashes and 83 semicolons. Convert
opportunistically, the same way you convert screenshots: text you write fresh
follows every rule, text you are already revising gets converted in the same
edit, and everything else stays as it is. Do not start a mass style pass. If a
page needs one, say so and let the user decide.

- **Talk to the reader as "you."** "You then see the Main Menu."
- **Keep the tone calm and confident.** Reserve exclamation points for the rare
  genuinely delightful moment. Prefer plain, declarative sentences otherwise.
- **Say it once.** Cut throat-clearing ("In order to…", "You should note
  that…"), redundant restatement, and hedging. When a procedure runs to more
  than two or three ordered steps, use a numbered list rather than a chain of
  "To begin… Next… Once you have…" paragraphs.
- **Write complete sentences. Do not open with a conjunction.** Never begin a
  sentence with "And". Join the thought to the sentence before it, or rephrase.
  The same goes for opening with "But" or "So."
- **Explain the *why*, but compress it.** A reader who understands the reason
  trusts the instruction. Keep the *why*, but state it in a clause rather than a
  paragraph. "The PiFinder dims the screen after a while to save battery and
  prevent glare" earns its keep. A three-sentence aside reassuring the reader
  that this is normal does not. When a caveat genuinely needs more room, put it
  in a `.. note::` rather than swelling the main flow.
- **Plain language over jargon.** When a technical term is unavoidable (plate
  solving, alt/az), define it in passing the first time, the way the quick start
  glosses "plate solving" as taking continuous pictures and comparing them.
- **Hardware keys are bold, uppercase:** the **UP** / **DOWN** arrows, **RIGHT**,
  **LEFT**, the **SQUARE** button, **+** and **-**. Menu and screen names are
  written in Title Case as they appear on the device (Settings Menu, Object
  Details, Push-To).
- **Describe menu navigation as a prose chain, not a glyph path.** Walk the
  reader along the route in plain verbs: "From the main menu, select Settings,
  scroll down to Advanced, then select PiFinder Type." Do not write `Settings →
  Advanced → PiFinder Type`. Arrow paths belong to the Mermaid menu trees in
  `menu_map.rst`. In running prose they read as jargon.

  Use **select** and **scroll** throughout, never "choose", "pick", or "go to".
  A route that mixes verbs makes the reader wonder whether the steps differ. The
  manual gets this wrong in several places, so copy the rule rather than the
  neighbouring page.

  Name each step in Title Case as it shows on the device. Anchor it when that
  helps the reader find it ("near the bottom of the main menu", "at the top of
  the Start menu"). For a destination you point at more than once, link it with
  a `:ref:` cross-reference to its section instead of respelling the whole path
  each time.

Voice check. Both of these carry the same information.

> **Yes.** Hold **SQUARE** and press **+** to brighten the screen, or **-** to
> dim it. At a dark site you can turn it right down to preserve your night
> vision.

> **No.** Brightness is adjustable via the SQUARE modifier key in combination
> with the increment/decrement keys — at a dark site the display can be turned
> right down, which will help to preserve your night vision.

The second version breaks four rules at once. It is passive ("is adjustable",
"can be turned"). It joins two sentences with an em-dash. It says "display"
where the manual says "screen". It chains auxiliaries ("will help to preserve").
None of those faults is dramatic on its own. Together they are what makes
documentation tiring to read at 2am.

## reStructuredText conventions

These are the patterns used across the existing pages. For anything not covered
here — tables, the full admonition list, code blocks, substitutions — read
`references/rst-conventions.md`.

**Headings** use an underline (the title may also have an overline). Keep one
character per level, consistently, within a page:

```
Page Title
==========

Major Section
-------------

Sub-section
~~~~~~~~~~~~
```

(Some pages overline *and* underline the page title with `=`; if the page you're
editing does that, match it.) Never skip a level or switch characters mid-page —
Sphinx infers the hierarchy from the order the characters first appear, so an
inconsistent ladder silently reorders your structure.

**Links to other pages** use `:doc:`, optionally with display text:

```
see the :doc:`Build Guide <build_guide>`
checkout the full :doc:`user_guide`
```

**Links to a section** use `:ref:` with the `autosectionlabel` form
`docname:section title`. Critically, **the label is lowercased** even though the
heading itself is Title Case:

```
heading in the file:   Settings Menu
reference to it:        :ref:`user_guide:settings menu`
with custom text:       :ref:`object images <user_guide:object images>`
```

**Images** point into a per-page folder under `images/`. Use `:width:` to place
two side by side:

```
.. image:: images/user_guide/options_menu_01.png

.. image:: images/quick_start/pf_front.jpeg
   :width: 45%
.. image:: images/quick_start/pf_rear.jpeg
   :width: 45%
```

Reference real, existing image files. If a feature needs a screenshot that
doesn't exist yet, you can usually **capture and prepare it yourself** — drive
the running app to the screen, grab it, and convert it (see *Preparing
screenshots* below), then drop it in the right `images/<page>/` folder. Only when
the shot genuinely can't be produced this way (e.g. it needs a real night sky,
specific hardware, or a physical setup) should you fall back to a clearly-named
placeholder path in the `.. image::` directive and flag, in your summary, that
the user needs to supply it. Never invent a filename for an image you haven't
actually produced.

**Notes** use the `note` admonition (body indented under it):

```
.. note::
   The PiFinder dims the screen after it's been idle for a while to save
   battery and prevent glare. The default is 30 seconds; you can change it in
   the :ref:`user_guide:settings menu`.
```

**External links:** `` `PiFinder.io <https://www.pifinder.io/>`_ `` — note the
trailing underscore.

## Preparing screenshots

Getting a doc-ready screenshot is two steps: **capture** the raw screen from a
running PiFinder, then **convert** it to the larger, brighter house style.

### Which panel to shoot

**Capture at 176×176 (rev4) by default** — that is what `pf_remote launch` now
does without being asked. New and re-taken screenshots are rev4 shots.

The manual still contains ~118 older 256×256 images captured from the 128×128
panel. **There is no mass-replacement job and you must not start one.** The rule
is opportunistic conversion:

- Any screenshot you take fresh → 176 px.
- Any existing screenshot **in a section you are already editing** → re-take it
  at 176 px as part of the same change.
- Everything else → leave it alone. Mixed image sizes across the manual are
  expected and accepted while it converts.

Shoot the 128 px panel (`--display headless`) only when the shot is specifically
illustrating v3/v2.5 hardware — for example a side-by-side in
"Which PiFinder do I have?".

### Step 1 — capture the raw screen (`pifinder-remote` skill)

You don't need real hardware. The **`pifinder-remote`** skill runs PiFinder
headlessly and lets you drive it like a user over its HTTP API — launch it,
press keys to navigate to the screen you're documenting, and save the live
display as a PNG. Read that skill's `SKILL.md` for the full command set;
the shape of it is:

```
S=.claude/skills/pifinder-remote/scripts/pf_remote.py

python3 $S launch                       # headless PiFinder at 176x176 (first run ~90s)
python3 $S launch -fb                   # ...plus the rev4 battery icon and a full
                                        #    simulated discharge (low-battery warnings)
python3 $S launch --display headless    # the 128x128 v3/v2.5 panel, when you need it
python3 $S key DOWN DOWN RIGHT          # navigate to the screen you want
python3 $S screen -o /tmp/raw_shot.png  # capture the current screen
python3 $S stop                         # clean shutdown when done
```

Use `-fb` for anything showing the title bar on rev4 — without it the battery
icon is absent, because plain `-fh` emulates rev3. It also runs a full discharge
lap, which is how you reach the low-battery popups and each battery bucket
without hardware.

After each key press, capture a fresh `screen` and **Read** the PNG to confirm
you're on the right screen before you keep it — menu order shifts between
versions, so the screen is the ground truth.

### Step 2 — convert to a doc-ready image (`screenshot_to_doc.py`)

Raw captures are red-only (the OLED is driven red to protect night vision), so
they're small and dim. The docs use larger, brighter images: the red intensity is
recolored onto a warm amber tint and scaled 2×. The amber recolor is what makes
them look "brighter" — don't fiddle with brightness yourself; the bundled tool
bakes in the house tint (`245,76,10`), the 2× scale, and crisp pixel upscaling.
At 2× a rev4 capture lands at **352×352**; the older 128 px shots are 256×256:

```
# one screenshot, named for where it lands in the manual:
python scripts/screenshot_to_doc.py /tmp/raw_shot.png \
    -o docs/source/images/user_guide/status_screen_docs.png

# several at once into a page's image folder (keeps each input's name):
python scripts/screenshot_to_doc.py /tmp/shot1.png /tmp/shot2.png \
    --out-dir docs/source/images/quick_start/
```

Keep the existing filename when you re-take a shot — the `.. image::` directive
then needs no edit and the diff shows exactly what changed.

Name outputs for their role in the docs, not after the raw capture — a reader
(and the `.. image::` directive) should see `status_screen_docs.png`, not
`raw_shot.png`. Run `python scripts/screenshot_to_doc.py -h` for the options
(`--resample lanczos` for smoother edges, `--tint`, `--scale`, `--force`). It
needs Pillow, which is already a PiFinder dependency — activate the project venv
if the import fails.

## Task workflows

### Documenting a feature in an existing page

This is the common case. A new menu, screen, or setting shipped and the manual
needs to describe it.

1. Find where it belongs. A user-facing setting goes under Settings in
   `user_guide.rst`; a new screen goes near related screens. Read the
   surrounding sections so your new one slots in at the right heading depth.
2. Write the section: lead with what it does and *why someone would want it*,
   then how to reach and operate it (which menu, which keys), then any caveats
   in a `.. note::`.
3. Wire up cross-references both ways where it helps — link from the quick start
   if it's something a first-timer hits, and `:ref:` to related sections.
4. Add `.. image::` directives where a screenshot clarifies things (see the
   placeholder guidance above).

### Creating a new page

1. Create `docs/source/<name>.rst` with a page title and the standard top
   `.. note::` about which software version the docs target, if the page is
   version-sensitive (copy the one from `quick_start.rst`).
2. **Register it in the toctree** in `docs/source/index.rst` — a new page that
   isn't in the toctree won't appear in the navigation and Sphinx will warn that
   it's an orphan. Insert it in the reading-order position that makes sense.
3. Create `docs/source/images/<name>/` for its screenshots.

### Polishing existing prose

This is where the house voice does most of its work, so read
`references/ste-style.md` first.

Work in this order. It goes from mechanical to judged, and the early passes
often make the later ones unnecessary:

1. **Split the joined sentences.** Find every em-dash and semicolon in the
   passage. Replace the ones welding two clauses together with a full stop.
   Section 5 of the reference has a pattern for each of the five ways this
   manual uses a dash.
2. **Fix the terminology.** Apply the approved-term table. This is the change a
   reader feels most and the one that is easiest to verify.
3. **Turn passive instructions active**, and start each procedural sentence with
   its verb.
4. **Cut what is left.** Throat-clearing, restatement, hedging.

Preserve the meaning, every cross-reference, and every image path. Keep the
scope tight: revise the passage you were asked about, not the whole page.

## Verify before you hand off

### Build the docs

Broken cross-references and malformed rST only show up at build time. Point the
output at a throwaway dir so you don't litter the repo:

```bash
cd docs
python -m sphinx -b html -n -q source /tmp/pifinder_docs_build
```

`-n` is "nitpicky" mode, which flags broken `:ref:` and `:doc:` targets. `-q`
suppresses the progress output, so the command prints **only** warnings and
errors. **The manual currently builds with zero warnings**, so anything that
appears is yours. Fix it. The two you are most likely to cause are "undefined
label" (a mistyped `:ref:`) and "toctree contains reference to nonexisting
document" (a new page you forgot to register).

Use the project venv. Sphinx needs `sphinxcontrib-mermaid` for `menu_map.rst`,
and a system Sphinx usually lacks it. If the build dies with "Could not import
extension sphinxcontrib.mermaid", you are on the wrong interpreter:

```bash
source python/.venv/bin/activate     # then re-run the build
```

If no interpreter has Sphinx, say so rather than skipping the check silently.
Offer `pip install -r docs/source/requirements.txt`.

### Check your own prose

The style rules are easy to verify on your own diff, and this catches the
lapses that survive a careful first draft:

```bash
git diff -U0 -- docs/source | grep '^+' | grep -nE '—|;'
```

Every hit needs a decision. A dash or semicolon joining two sentences is a rule
1 violation, so split it. Section 5 of `references/ste-style.md` covers the
cases where a dash can stay. Then re-read your added text once against the
approved-term table, which is the rule that slips most often.

When you summarise your work, list the files you changed, any screenshots the
user still needs to capture, and the result of the build check.

## Stay in your lane

- Edit `.rst` under `docs/source/`, never the `docs/*.md` stubs.
- Don't touch `docs/ax/*/CONTEXT.md` or `docs/adr/*` — that's the domain-model
  documentation handled by the `grill-with-docs` skill.
- Don't restructure the toctree or rename pages unless asked; those are
  navigation-wide changes.
