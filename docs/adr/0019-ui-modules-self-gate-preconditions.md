# UI modules self-gate their preconditions (enter-then-back-out), not a menu hard-block

A screen that depends on a runtime precondition is still opened normally from the
menu; the **module itself** checks the precondition and, when it is unmet,
renders an explanatory notice in place of its normal UI and makes its inputs
inert. The user reads the notice and **backs out** (LEFT/Cancel) on their own. We
do **not** block navigation at the menu layer.

The motivating case is manual **Set Time/Date** (`UITimeEntry`, chaining to
`UIDateEntry`). Entry is interpreted in the observer's **local timezone**, which
we only derive from a **location fix** — `callbacks.set_time` / `set_datetime`
read `shared_state.location().timezone`. Without a fix the entered time would be
localised against a bogus UTC zone (the bug behind [ADR-0018](./0018-civil-datetime-stored-utc-aware.md)).
So the screen requires a location. This ADR fixes *where* that requirement is
enforced: inside the screen, not at the menu item that opens it.

## The navigation mechanic that makes a hard-block possible

`UITextMenu.key_right` (`ui/text_menu.py`) dispatches a menu item's `"callback"`
**before** its `"class"`, and the callback's return value propagates straight out
of `key_right`: a callback that returns without pushing anything simply cancels
the navigation. A `"class"` item is pushed unconditionally; its optional
`pre_callback` runs first but its return value is **discarded**, so a
`pre_callback` cannot refuse the push. Therefore a plain `"callback"` is the
*only* lever that can decline to open a screen — and this ADR chooses not to pull
it.

## Considered options

- **Menu-layer hard block (a gate callback).** The first cut of this change
  (PR #512) routed Set Time/Date through `callbacks.enter_time_entry`, which
  checked `location().lock` and, when unlocked, showed a 2-second "Set location
  first" popup and returned **without** opening the screen. Rejected: it hides
  the feature — the user never sees the screen and never learns what it needs —
  and it splits the precondition across two layers, forcing the menu callback to
  know an internal fact about the screen (that it needs a location's zone) that
  already lives in the screen's own callbacks.
- **Self-gating module (chosen).** The precondition lives in exactly one place —
  the module that depends on it. The feature stays discoverable; the on-screen
  message teaches the user what to do; the menu stays a dumb router that always
  opens the screen.
- **Disable / grey out the menu item.** Rejected: the menu has no "disabled item"
  affordance, and a greyed item is just a quieter hard-block with the same
  discoverability loss and no room to explain *why* or *what to do next*.

## Consequences

- **The check is live** (re-read every frame via `_location_locked`), so the
  entry boxes appear the instant a fix locks while the user is sitting on the
  screen — no need to back out and re-enter.
- **Every module owning the precondition self-gates, even when it is currently
  unreachable while unmet.** `UIDateEntry` is only reached by confirming the
  (already gated) time screen, so it cannot be entered without a fix today; it
  still carries the same guard so it stays correct if it is ever surfaced
  directly (e.g. relocated in the menu tree).
- **The exit callback must be suppressed when gated.** A module fires its
  `custom_callback` (`set_time` / `set_datetime`) from `inactive()` on the way
  out; a gated screen early-returns there so it never runs the callback against
  the bogus UTC zone the gate exists to prevent.
- **Rendering is shared, the precondition is not.** A reusable
  `UIModule.draw_gate_message()` draws the centred notice + a Cancel hint; the
  precondition predicate stays local to each screen, so the base owns the generic
  "how to show a gate" and each module owns "what it needs." This mirrors the
  self-contained-in-the-UI stance of [ADR-0005](./0005-focus-hfd-self-contained-in-ui.md).
- **Trade-off accepted:** a hard-block would save one wasted keypress (the user
  opens a screen they cannot use yet). We judge discoverability and single-owner
  precondition logic worth that keypress.
- Companion glossary: [`docs/ax/ui/CONTEXT.md`](../ax/ui/CONTEXT.md) (Self-gating
  module).
