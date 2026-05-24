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
| `user_guide.rst` | Full reference for every menu, screen, and setting |
| `catalogs.rst` | Object catalogs included |
| `build_guide.rst` | Assembling the hardware |
| `v25_upgrade.rst` | Upgrading a v2 unit |
| `software.rst` | Flashing / updating the software image |
| `skysafari.rst` | SkySafari / planetarium integration |
| `dev_guide.rst`, `dev_arch.rst` | Contributor / architecture docs |
| `BOM.rst` | Bill of materials |

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
voice. And if anything there conflicts with the code or the existing docs, trust
the code/docs and flag the conflict to the user rather than documenting the
discrepancy.

## The house voice

The manual is written warmly and directly, as if Richard (the creator) is
walking a friend through their new telescope accessory. Match it:

- **Talk to the reader as "you."** "You'll then see the Main Menu appear."
- **Be encouraging and a little excited.** Exclamation points are welcome where
  something is genuinely delightful ("point it at the sky!"). Don't force them.
- **Explain the *why*, not just the *what*.** The existing docs constantly say
  things like "This helps save battery power and can prevent glare at the
  eyepiece." A reader who understands the reason trusts the instruction.
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
doesn't exist yet but you have a **raw PiFinder capture** for it, convert it to a
doc-ready image with the bundled tool (see *Preparing screenshots* below) and
drop it in the right `images/<page>/` folder. If you have no capture at all,
**don't invent a filename** — add the `.. image::` directive with a clearly-named
placeholder path and call out, in your summary to the user, that they need to
capture and supply that screenshot.

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

Raw PiFinder captures are 128×128 and rendered red-only (the OLED is driven red
to protect night vision), so straight out of the device they're tiny and dim. The
docs use larger, brighter images: the red intensity is recolored onto a warm
amber tint and scaled up to 256×256. The amber recolor is what makes them look
"brighter" — you don't need to fiddle with brightness yourself.

Use the bundled tool instead of doing this by hand — it bakes in the house tint
(`245,76,10`), the 2× scale, and crisp pixel upscaling:

```
# one screenshot, named for where it lands in the manual:
python scripts/screenshot_to_doc.py <raw.png> \
    -o docs/source/images/user_guide/status_screen_docs.png

# several at once into a page's image folder (keeps each input's name):
python scripts/screenshot_to_doc.py <raw1.png> <raw2.png> \
    --out-dir docs/source/images/quick_start/
```

Name outputs for their role in the docs, not after the raw capture — a reader
(and the `.. image::` directive) should see `status_screen_docs.png`, not
`IMG_4821.png`. Run `python scripts/screenshot_to_doc.py -h` for the options
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
