# Simplified technical English for the PiFinder manual

This file backs the house-voice rules in `SKILL.md`. Read it when you write or
revise more than a paragraph, when you are unsure which word to use for
something, or when you need to replace an em-dash and want a pattern that works.

Contents:

1. [How to apply these rules to a manual that predates them](#1-how-to-apply-these-rules-to-a-manual-that-predates-them)
2. [The seven rules, with worked examples](#2-the-seven-rules-with-worked-examples)
3. [Approved terms](#3-approved-terms)
4. [Distinctions worth keeping](#4-distinctions-worth-keeping)
5. [Replacing em-dashes and semicolons](#5-replacing-em-dashes-and-semicolons)

---

## 1. How to apply these rules to a manual that predates them

The manual was written before this style existed. A survey of the 13 user-facing
pages found 259 em-dashes, 83 semicolons, and heavy synonym drift. You cannot fix
that in one pass, and you must not try.

Convert opportunistically, exactly as you do with screenshots:

- Text you write fresh follows every rule below.
- Text you are already revising for another reason gets converted in the same
  edit.
- Everything else stays as it is.

A page with mixed style is expected while the manual converts. A pull request
that rewrites 200 sentences nobody asked about is not. If you think a page needs
a full style pass, say so and let the user decide.

---

## 2. The seven rules, with worked examples

Every "before" line below is real text from the manual, with its location.

### Rule 1 — one idea per sentence

Do not use an em-dash or a semicolon to weld two sentences together. Use a full
stop. A reader in the dark can lose their place inside a long sentence and has to
start it again.

> **Before** (`quick_start.rst:330`)
> The default is 30 seconds; you can change it, or turn it off, in the Settings menu.
>
> **After**
> The default is 30 seconds. You can change it, or turn it off, in the Settings menu.

> **Before** (`quick_start.rst:348`)
> ...which happens automatically — but the GPS Status screen lets you monitor progress.
>
> **After**
> This happens automatically. The GPS Status screen lets you monitor progress.

### Rule 2 — active voice

Name the actor. Use the passive only when the actor is genuinely unknown or does
not matter. The reader needs to know whether they do something or the PiFinder
does it.

> **Before**
> Brightness is adjustable via the SQUARE modifier key.
>
> **After**
> Hold **SQUARE** and press **+** to brighten the screen.

Passive is correct when nobody in particular acts:

> The catalog images are downloaded during the first update.

### Rule 3 — start instructions with a command verb

Procedures are imperative. The reader is holding the PiFinder and wants to know
what to do with it.

> **Before**
> The next thing you will want to do is to select the Focus option.
>
> **After**
> Select Focus.

A short condition or location may come first. This keeps the prose readable and
is not a violation:

> At a dark site, turn the brightness down.
> From the main menu, select Settings.

What to avoid is burying the verb behind a clause: "Once you have finished
aligning, what you should then do is select Objects."

### Rule 4 — simple tenses

Use simple present, simple past, and simple future. The present tense carries
almost everything in a manual.

> **Before**
> The PiFinder will have finished booting by the time you have mounted it.
>
> **After**
> The PiFinder finishes starting up while you mount it.

### Rule 5 — no auxiliary verb chains

Two auxiliaries stacked together make a sentence hard to parse for a
second-language reader.

| Avoid | Use |
|---|---|
| you will be able to see | you see |
| it should have been charged | charge it first |
| you may want to be sure that | check that |
| this can be adjusted | adjust this |

"Can" and "may" on their own are fine. `You can turn the screen off` is good
English and good STE.

### Rule 6 — at most three nouns in a row

The manual is already good at this. Only one true four-noun string survives
(`deep sky catalog images`, in `software.rst:10` and `sd_card.rst:9`), and the
fix is the hyphen the manual already uses elsewhere: **deep-sky catalog images**.

Treat three as the ceiling, not the target. When a string gets long, hyphenate
the modifier or add a preposition:

- `camera exposure time setting` → `the exposure time setting for the camera`
- `battery charge status indicator` → `the battery indicator`

Hyphenated compounds count as one noun. `push-to offsets` and `real-time
pointing information` are fine.

### Rule 7 — one word per concept

Use the table in section 3. If you need a word that is not in it, pick the one
the manual already uses most, then use only that word for the rest of the page.

---

## 3. Approved terms

Counts are occurrences across the 13 user-facing pages, and they are why each
winner was chosen.

| Concept | Use this | Not these | Evidence |
|---|---|---|---|
| Operate a key | **press** | push, tap, hit, click | press 75, push 3, tap 2 |
| Long-press one key | **press and hold** | hold down, long-press | phrasing currently varies |
| Hold a modifier and press another key | **hold X and press Y** | press and hold X and press Y | see §4 |
| Choose a menu entry | **select** | choose, pick, activate | select 60, choose 49, pick 16 |
| The physical screen | **the screen** | the display, the panel, the OLED | screen 168, display 23 |
| The product | **the PiFinder** | the unit, the device, the finder | PiFinder 453, unit 17, device 2 |
| A row in a menu | **menu item** | entry, option (see §4) | currently interchangeable |
| One of several values | **option** | setting, choice, item (see §4) | option 45 |
| Move within a menu | **scroll** | navigate, browse, go to, move to | scroll 20, browse 6, navigate 5 |
| Turn the power on (what the reader does) | **turn on** | power up, switch on, start up | turn on 9, power on 3 |
| Turn the power off (what the reader does) | **turn off** | power down, switch off | turn off 9, switch off 5 |
| The machine's own startup sequence | **boot** | start, start up, startup, power-up | boot 14 — see §4 |
| The act of shutting down | **shutdown** (noun) | shut-down | shutdown 22 |
| Shut the PiFinder down | **shut down** (verb) | shutdown as a verb | shut down 6 |
| A catalog object | **object** | target, DSO | object 208, target 22, DSO 11 |
| The user's telescope | **telescope** | scope, OTA, tube | scope 72, telescope 67 — see below |
| The category of object | **deep-sky object** | deep sky object, DSO | hyphenate; DSO only for the on-screen label |
| Solving a camera frame | **plate solve** (verb and noun) | plate-solve, plate-solving as a verb | open form, 10 vs 4 |
| Describing a thing that solves | **plate-solving** (adjective) | plate solving before a noun | hyphenate before a noun |
| Go up one menu level | **go back** | return, exit, back out, leave | back 47, return 17, exit 5 |
| Leave a tool or mode | **exit** | leave, quit, dismiss | reserve for modes, see §4 |

Once a page has said "plate solve" and explained it, plain **solve** is fine for
the rest of that page. The manual already does this 67 times and it reads well.

### "telescope", not "scope"

This is the one entry in the table that had no evidence winner. The manual used
"scope" 72 times and "telescope" 67, near enough a coin flip, and often both in
one paragraph. **The maintainer settled it: use telescope.** It is unambiguous
for a second-language reader, which is much of the reason this style exists.
"Scope" is shorter, but it is jargon, and it carries other meanings in ordinary
English.

The manual has been converted, so there is nothing left to sweep. What matters
now is not undoing it, and not over-applying it.

**Keep "scope" in these four cases.** Each names something that is *not* the
reader's telescope, so renaming it would be a factual error, not a style fix:

| Keep | Why |
|---|---|
| **polar scope** | The sighting device inside an equatorial mount. "Polar telescope" is not a term anyone uses, and the Polar Alignment section is largely about aligning *without* one. |
| **finder scope** | A separate optical finder. The manual mentions it to contrast it with the PiFinder. |
| **scope type** (SkySafari) | A third-party field label, confirmed against `images/SkySafari/IMG_4796.jpeg`. Quote other products' interfaces exactly. |
| **OTA**, **finder shoe**, **Dobsonian** | Fixed compounds and product names the reader will meet elsewhere. |

The general rule behind the table: quote any interface exactly as it is labelled,
whether it is PiFinder's or someone else's, and do not rename existing headings
just to apply a term.

### The article on "PiFinder"

Write **the PiFinder** when you mean the device in front of the reader. Write
**your PiFinder** when ownership matters, such as warranty or shipping. Write
bare **PiFinder** only in headings and product names.

Never write "your device" for the PiFinder. In `skysafari.rst` "your device"
already means the reader's phone, and the collision is confusing.

---

## 4. Distinctions worth keeping

Do not flatten these. They carry real meaning.

**menu item vs option.** A *menu item* is a row you can select in a menu. An
*option* is one of the values that item offers. "Select the Sleep Time menu item,
then choose an option" is wrong on the second verb; write "then select an
option."

**The three key gestures.** These are different physical actions with different
results, and each has one correct phrasing. Do not collapse them.

| Gesture | Write it as | Example |
|---|---|---|
| A momentary press | `press **KEY**` | Press **RIGHT** to open the menu. |
| A long press on one key | `press and hold **KEY**` | Press and hold **LEFT** for a second to return to the main menu. |
| A modifier chord | `hold **KEY** and press **KEY**` | Hold **SQUARE** and press **+** to brighten the screen. |

The chord form is the one exception to "press and hold". "Hold **SQUARE** and
press **+**" describes two keys at once and is already clear. Writing "press and
hold **SQUARE** and press **+**" makes it worse, not more consistent.

**object vs Custom Targets.** *Object* is the general term. *Custom Targets* is a
feature name and keeps its capitals and its noun. Do not use "target" as a plain
synonym for object. A one-off coordinate the reader enters by hand is a **Custom
Target**. An entry that arrives from an observing list is an **object**.

**turn on vs boot.** These are not synonyms, and collapsing them causes real
damage. **Turn on** is what the reader does to the power button or switch.
**Boot** is the machine's own startup sequence, which continues long after the
reader has let go.

The distinction is load-bearing here. "The PiFinder won't boot" and "The PiFinder
won't turn on" are different faults with different fixes: a bad SD card lets the
unit power on and then fail to boot. Two headings depend on the word, and
headings are frozen cross-reference targets:

- `sd_card.rst` — "First boot"
- `troubleshooting.rst` — "The screen is blank, or it won't finish booting"

So write "turn the PiFinder on", and "the first boot takes longer than usual".

**go back vs exit.** **LEFT** goes back one menu level, so write "press **LEFT**
to go back." Leaving a mode or tool entirely is "exit", as in "press **SQUARE**
to exit the Quick Menu."

**screen (hardware) vs screen (a page of the UI).** Both are correct and the
manual uses both. The context nearly always disambiguates. If a sentence is
genuinely ambiguous, write "the Status screen" for the UI and "the PiFinder's
screen" for the hardware.

---

## 5. Replacing em-dashes and semicolons

The manual's em-dashes fall into five patterns. Each has a fix that does not
lose meaning.

**1. Restating or defining the thing just named** (the most common single-dash
use). Make it a second sentence.

> **Before** (`user_guide.rst:311`)
> The number in the upper right is the **contrast reserve** — an estimate of how
> easily the object stands out.
>
> **After**
> The number in the upper right is the **contrast reserve**. It estimates how
> easily the object stands out from the sky background.

**2. A paired aside.** Use commas, or split the sentence.

> **Before** (`quick_start.rst:27`)
> This process — called *plate solving* — runs continuously.
>
> **After**
> This process, called *plate solving*, runs continuously.

**3. Joining two independent clauses.** Use a full stop. This is rule 1.

**4. Introducing the values a setting accepts** (mostly in `menu_map.rst`). Use a
fixed construction so every entry reads the same way.

> **Before** (`menu_map.rst:219`)
> Menu scrolling animation speed — Off, Fast, Medium, or Slow.
>
> **After**
> Menu scrolling animation speed. Values: Off, Fast, Medium, Slow.

**5. A trailing cross-reference.** Make it its own sentence.

> **Before**
> ...you can change it later — see :ref:`user_guide:settings menu`.
>
> **After**
> ...you can change it later. See :ref:`user_guide:settings menu`.

Semicolons are nearly always pattern 3. Replace them with a full stop.

### Where a dash is still allowed

A dash that punctuates a single idea, rather than joining two, is acceptable when
the alternative is clumsy. An interrupted or trailing thought in a `.. note::` is
the usual case. If you can use a full stop without losing the meaning, use the
full stop.
