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
Your job with this skill is to add or improve pages that read like they were
written by the same person who wrote the rest of the manual — same warm voice,
same rST conventions, same cross-reference style — so a reader can't tell where
the existing docs end and yours begin.

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

**Section in `user_guide` vs standalone page** — a topic earns its own page only
when readers *arrive at it directly* with a task in hand (search, a Discord
answer, a cross-page link) **and** it is *separable* from the guide's
operate-and-observe storyline (a sentence + link suffices in its place).
Otherwise it's a `user_guide` section. Standalone page URLs get linked from the
wild — don't merge or rename pages casually. Rationale and worked examples:
`docs/adr/0010-user-docs-page-granularity.md`.

**Before writing a single line, read the page you're about to touch (or the
closest sibling).** The fastest way to match the house style is to mirror the
section that already lives next to your change — its heading depth, how it
introduces images, how it refers to other pages. The conventions below are the
rules; the neighbouring text is the worked example.

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

The manual is written warmly and directly, but it stays measured and
professional — clear guidance from someone who knows the instrument well, not
breezy chat. It is also **lean**: the reader is usually at the eyepiece in the
dark, so every sentence earns its place. Keep the warmth, cut the padding. Match
it:

- **Talk to the reader as "you."** "You'll then see the Main Menu appear."
- **Be warm but measured.** Keep the tone calm and confident rather than
  breathless. Reserve exclamation points for the rare genuinely delightful
  moment and prefer plain, declarative sentences the rest of the time.
- **Be succinct.** Say it once, in as few words as carry the meaning. Cut
  throat-clearing ("In order to…", "You should note that…"), redundant
  restatement, and hedging. Favour the active voice and concrete verbs. When a
  procedure runs to more than two or three ordered steps, prefer a numbered list
  over a chain of "To begin… Next… Once you have…" paragraphs.
- **Write complete sentences; don't open with a conjunction.** Never begin a
  sentence with "And" — join the thought to the sentence before it, or rephrase.
  The same goes for opening with "But" or "So."
- **Explain the *why*, but compress it.** A reader who understands the reason
  trusts the instruction, so keep the *why* — but state it in a clause, not a
  paragraph. "The PiFinder dims the screen after a while to save battery and
  prevent glare" earns its keep; a three-sentence aside reassuring the reader
  that this is normal usually does not. When a caveat genuinely needs more room,
  put it in a `.. note::` rather than swelling the main flow.
- **Plain language over jargon.** When a technical term is unavoidable (plate
  solving, alt/az), define it in passing the first time, the way the quick start
  glosses "plate solving" as taking continuous pictures and comparing them.
- **Hardware keys are bold, uppercase:** the **UP** / **DOWN** arrows, **RIGHT**,
  **LEFT**, the **SQUARE** button, **+** and **-**. Menu and screen names are
  written in Title Case as they appear on the device (Settings Menu, Object
  Details, Push-To).

Voice check — prefer the left:

> "Hold **SQUARE** and press **+** to brighten the screen, or **-** to dim it.
> At a dark site you can turn it right down to preserve your night vision."

over

> "Brightness is adjustable via the SQUARE modifier key in combination with the
> increment/decrement keys."

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

### Step 1 — capture the raw screen (`pifinder-remote` skill)

You don't need real hardware. The **`pifinder-remote`** skill runs PiFinder
headlessly and lets you drive it like a user over its HTTP API — launch it,
press keys to navigate to the screen you're documenting, and save the live
128×128 display as a PNG. Read that skill's `SKILL.md` for the full command set;
the shape of it is:

```
S=.claude/skills/pifinder-remote/scripts/pf_remote.py

python3 $S launch                       # start headless PiFinder (first run ~90s)
python3 $S key DOWN DOWN RIGHT          # navigate to the screen you want
python3 $S screen -o /tmp/raw_shot.png  # capture the current 128x128 screen
python3 $S stop                         # clean shutdown when done
```

After each key press, capture a fresh `screen` and **Read** the PNG to confirm
you're on the right screen before you keep it — menu order shifts between
versions, so the screen is the ground truth.

### Step 2 — convert to a doc-ready image (`screenshot_to_doc.py`)

Raw captures are 128×128 and red-only (the OLED is driven red to protect night
vision), so they're tiny and dim. The docs use larger, brighter images: the red
intensity is recolored onto a warm amber tint and scaled to 256×256. The amber
recolor is what makes them look "brighter" — don't fiddle with brightness
yourself; the bundled tool bakes in the house tint (`245,76,10`), the 2× scale,
and crisp pixel upscaling:

```
# one screenshot, named for where it lands in the manual:
python scripts/screenshot_to_doc.py /tmp/raw_shot.png \
    -o docs/source/images/user_guide/status_screen_docs.png

# several at once into a page's image folder (keeps each input's name):
python scripts/screenshot_to_doc.py /tmp/shot1.png /tmp/shot2.png \
    --out-dir docs/source/images/quick_start/
```

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

Tighten for clarity and fix anything that's drifted from the voice above —
passive constructions, undefined jargon, missing "why." Preserve meaning and
every working cross-reference and image path. Don't rewrite wholesale; the
existing manual has a settled voice and your edits should disappear into it.

## Verify before you hand off

Broken cross-references and malformed rST are the easy mistakes here, and they
only show up at build time. Build the docs and check for warnings — point the
output at a throwaway dir so you don't litter the repo:

```bash
cd docs
# Sphinx + theme are pinned in docs/source/requirements.txt
sphinx-build -b html -n source /tmp/pifinder_docs_build 2>&1 | grep -iE "warning|error"
```

`-n` is "nitpicky" mode, which flags broken `:ref:`/`:doc:` targets. A clean run
prints nothing from the grep. Resolve any warning that names a file you touched —
especially "undefined label" (a mistyped `:ref:`) and "toctree contains
reference to nonexisting document." If `sphinx-build` isn't installed, say so
rather than skipping the check silently; offer `pip install -r
docs/source/requirements.txt`.

When you summarise your work, list the files you changed, any screenshots the
user still needs to capture, and the result of the build check.

## Stay in your lane

- Edit `.rst` under `docs/source/`, never the `docs/*.md` stubs.
- Don't touch `docs/ax/*/CONTEXT.md` or `docs/adr/*` — that's the domain-model
  documentation handled by the `grill-with-docs` skill.
- Don't restructure the toctree or rename pages unless asked; those are
  navigation-wide changes.
