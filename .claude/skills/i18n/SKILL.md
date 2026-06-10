---
name: i18n
description: PiFinder's internationalization (i18n) workflow — marking strings for translation, running the Babel extract/update/compile pipeline, adding or updating language translations, and filling in missing msgstr entries in .po files. Use whenever the user mentions translations, i18n, localization, locale, gettext, Babel, .po/.pot/.mo files, language support, or asks about adding/updating a language. Also use when reviewing a diff that touches user-visible UI strings and you need to check whether they're wrapped for translation.
---

# PiFinder i18n

PiFinder uses standard Python `gettext` with Babel for extraction and compilation. Translations live in `python/locale/` and are loaded at startup based on the `language` config option.

Supported languages today: `de`, `es`, `fr`, `zh` (plus `en` as the source/fallback).

## Where things live

- **Source strings extractor config:** `python/babel.cfg`
- **Workflow runner:** `python/noxfile.py` → `babel` session
- **Translation files:** `python/locale/messages.pot` (template) and `python/locale/<lang>/LC_MESSAGES/messages.po` (per-language)
- **Runtime install:** `python/PiFinder/main.py` calls `gettext.translation(...).install()` near startup, making `_()` a builtin everywhere
- **Flask web server:** `python/PiFinder/server.py` uses `flask_babel`'s `gettext` (imported, not builtin)

Run all `nox` and `pybabel` commands from `python/` with the project's virtualenv active.

## Marking strings for translation

Wrap user-visible strings with `_()`. It's installed as a Python builtin by `main.py` at startup, so no import is needed in normal modules. Ruff is configured to recognize `_` (see `pyproject.toml`), so there are no lint warnings.

**Good:**

```python
self.error_message = _("Can't plot")
status = _("Galaxy")
```

**Good — formatting with named placeholders:**

```python
_("{lat:.2f}, {lon:.2f}\n{alt}m alt").format(lat=lat, lon=lon, alt=alt)
```

Named placeholders matter: translators can reorder them, and the msgid stays stable across value changes.

**Avoid — f-strings inside `_()`:**

```python
_(f"  {self._SQUARE_} START ALIGN")     # bad
_(f"{count} objects")                    # bad
```

Babel extracts the f-string verbatim including the interpolated expression, so the msgid changes every time the interpolated value does and translators can never produce a stable match. There are a few of these in `python/PiFinder/ui/align.py` — they're legacy, not a pattern to follow.

**Avoid — concatenation:**

```python
_("Hello, ") + name + _("!")             # bad, fragments are untranslatable in context
_("Hello, {name}!").format(name=name)    # good
```

**Special case — `python/PiFinder/obj_types.py`:** This file defines a local `_` at the top that returns its argument unchanged. That's intentional — it lets `pybabel extract` pick up the object-type strings as msgids while the module is imported at a time when the global `_()` may not yet be installed. Don't "fix" it. The bottom of the file has a comment explaining the convention.

**Plurals and contexts:** Not currently used in PiFinder. If genuinely needed, prefer rewording over introducing `ngettext`/`pgettext` for the first time without discussion — it'll add complexity to every existing translator's workflow.

**Translator hints:** Add a `# TRANSLATORS:` comment immediately above the string when the source text is ambiguous out of context. Babel's `-c TRANSLATORS` flag pulls these into the .po file. Example from `obj_types.py`:

```python
"Gx": _("Galaxy"),  # TRANSLATORS: Object type
```

## The extract → update → compile workflow

Whenever source strings change (added, edited, or removed), run:

```bash
cd python/
nox -s babel
```

This runs three pybabel steps in order:

1. **extract** — scans `./PiFinder` per `babel.cfg`, regenerates `locale/messages.pot`
2. **update** — merges new/changed msgids from the .pot into every existing `locale/<lang>/LC_MESSAGES/messages.po`, marking unchanged strings, leaving new ones as empty `msgstr ""`, and flagging close matches as `#, fuzzy`
3. **compile** — builds the `.mo` binaries the runtime actually reads

If you only need one step (e.g., just compiling after hand-editing a .po), run the matching `pybabel` command directly from `python/`:

```bash
pybabel extract -F babel.cfg -c TRANSLATORS -o locale/messages.pot ./PiFinder
pybabel update  -i locale/messages.pot -d locale
pybabel compile -d locale
```

Commit both the updated `.po` files and the regenerated `.mo` files (the repo currently checks in `.mo`).

## Adding a new language

Use the ISO 639-1 code (two letters, lowercase). From `python/`:

```bash
pybabel init -i locale/messages.pot -d locale -l <code>
```

This creates `locale/<code>/LC_MESSAGES/messages.po` seeded from the current template. Then:

1. Fill in the `msgstr ""` entries (see "Generating translations" below).
2. Run `nox -s babel` to compile.
3. Add the language to the validated set in `python/PiFinder/main.py` (search for the existing `de`/`es`/`fr`/`zh` list — there's a validation site around the `--lang` argument handling, and a Flask fallback list in `python/PiFinder/server.py`). Both spots need the new code or `--lang <new>` will be rejected and the web server won't recognize it.
4. Verify by starting the app with `--lang <code>` and walking through a few menus.

## Generating translations (filling in `msgstr`)

When asked to translate missing strings in a `.po` file:

1. **Find the gaps.** Empty entries look like:
   ```po
   msgid "Can't plot"
   msgstr ""
   ```
   Also watch for `#, fuzzy` markers — those are Babel's guesses from `pybabel update` and need human review:
   ```po
   #, fuzzy
   msgid "Set location"
   msgstr "Lieu actuel"
   ```
   Either correct the translation and **remove the `#, fuzzy` line** (otherwise gettext ignores the entry at runtime), or replace it entirely.

2. **Translate with context in mind.** PiFinder is a telescope finder — many strings are astronomical terms (object types, catalog names), short UI labels constrained by a tiny OLED display, or status messages. Prefer concise translations that fit similar visual width to the English. When the `# TRANSLATORS:` comment exists, follow its guidance.

3. **Preserve placeholders and whitespace exactly.** If the msgid contains `{lat:.2f}` or `\n` or trailing spaces, the msgstr must contain the same tokens. Reordering named placeholders is fine; renaming them is not.

4. **Don't translate technical identifiers.** Catalog codes (NGC, M, IC), units (°, m, px), and proper nouns generally stay as-is.

   Some abbreviations must **never** be translated, transliterated, or expanded — even when the words around them are. Keep them as-is:

   - **`EQ`** — equatorial coordinate mode (e.g. `EQ (Auto)`, `EQ (North-up)`, `EQ (South-up)`). Keep verbatim; never translate or expand.
   - **`RA`** (acronym for Right Ascension) and **`Dec`** (abbreviation for Declination) — keep as abbreviations; never expand or localize. Use the form **`RA/Dec`** — note `Dec`, not `DEC` — even when a source string is written `RA/DEC` or `DEC:`. `RA` stays uppercase; only the declination part is `Dec`.
   - **`Alt/Az`** — altitude/azimuth. Keep verbatim; do not translate or reorder the two parts.
   - **`GPS`** — any message containing `GPS` keeps it as `GPS`; it's recognized under that acronym across languages.

   These show up in strings like `EQ (North-up)`, `RA/DEC Disp.`, `RA:` / `DEC:`, `Alt/Az`, and `GPS Settings`. Translate only the *surrounding* words (e.g. "Settings", "Disp.") and render the abbreviation in its canonical form (`RA/Dec`, `EQ`, `Alt/Az`, `GPS`).

5. **After editing, recompile:**
   ```bash
   cd python/ && pybabel compile -d locale
   ```

6. **Sanity check** by running the app with `--lang <code>` and confirming the strings render correctly (no truncation, no mojibake, no broken format strings).

When you're filling in many entries at once, do them in batches and call out any strings where you weren't sure of the intended meaning so the maintainer can sanity-check.

### Mark AI-generated translations for human review

Any `msgstr` value that you (Claude) or any other AI system produces — including light edits or re-orderings of a prior translation — must be tagged with a translator comment on the line directly above the entry, so a human reviewer can find and validate it later:

```po
# AI-TRANSLATED (claude): needs human review
msgid "Can't plot"
msgstr "Impossible de tracer"
```

The exact prefix `AI-TRANSLATED` matters — it's what makes the entries greppable across all `.po` files. Include the model or system name in parentheses when known (e.g., `claude`, `gpt-4`, `deepl`) so reviewers can weigh source reliability. A reviewer's workflow looks like:

```bash
grep -rn "AI-TRANSLATED" python/locale/
```

When a human confirms the translation is correct, they **remove the comment**. An entry without the marker is treated as human-validated. This means: don't add the marker to translations you didn't touch, and don't strip it from entries you only re-formatted.

Why a plain `# ` comment rather than `#, fuzzy`: the `fuzzy` flag tells gettext to ignore the msgstr at runtime, so users in the target language would see the English fallback instead of your draft translation. That defeats the point of doing the work. The `AI-TRANSLATED` comment leaves the translation live in the UI while still being unmistakably findable.

If you have low confidence in a specific translation (technical term, ambiguous context, cultural nuance), pair the marker with `#, fuzzy` *in addition* — that string falls back to English until a human approves, which is the safe choice when getting it wrong would be worse than showing English:

```po
# AI-TRANSLATED (claude): unsure of astronomical convention in target language
#, fuzzy
msgid "Right Ascension"
msgstr "Ascension droite"
```

## Reviewing diffs for i18n correctness

When asked to audit a diff or PR for i18n issues, check:

- **New user-visible strings in `python/PiFinder/ui/`, menus, server templates, or error messages — are they wrapped in `_()`?** Internal log messages, exception messages for developers, and debug strings are usually fine to leave alone.
- **F-strings or concatenation inside `_()`?** Flag as bugs (see "Avoid" examples above).
- **String formatting with positional `{}` or `%s`?** Push toward named placeholders — translators need them.
- **Strings split across lines for code formatting?** Make sure the joined result is still one msgid, not multiple fragments.
- **Was `nox -s babel` run?** If `.po`/`.pot` files weren't updated alongside the string changes, the translations are now stale.

## Quick verification

After any translation work, the fastest end-to-end check:

```bash
cd python/
nox -s babel                                                # extract/update/compile
python -m PiFinder.main -fh --camera debug --keyboard local -x --lang <code>
```

Watch for the strings you touched to render in the target language. If anything still shows in English, the most common causes are: forgot to compile (`.mo` is stale), the string isn't actually wrapped in `_()`, or the entry is still marked `#, fuzzy`.
