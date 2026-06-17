# List notes are interaction-sourced, not scanned from disk

A **list note** is the per-target description an observing list carries; we show it
alongside an object's catalog description (see the Catalog
[CONTEXT.md](../ax/catalog/CONTEXT.md)). We attach notes **at list-load time**: when
the user opens an observing list, `read_list` records that list's note onto every
**resolved** object it contains, stored in `CompositeObject.list_notes` keyed by the
list name. Because the resolved object is the shared catalog instance, notes
**accumulate for the session** across every list opened and surface wherever the
object is later viewed — including when it is reached by browsing its catalog
directly rather than through the list. They are not persisted (gone on restart) and
there is no removal path within a session. Coordinate objects carry no list note;
their list text becomes their own description, as they have nothing else.

## Considered options

- **Interaction-sourced (chosen)** — notes come only from lists the user actually
  opens this session. Zero cost beyond reading lists the user wanted anyway, and the
  cross-list aggregation ("this object is on several of my lists") falls out for free
  as opened lists accumulate on the shared object.
- **Data-sourced (rejected)** — scan every list file on disk so an object carries
  notes from any list mentioning it, with no interaction. Rejected because it needs a
  background indexer plus a cache invalidated on file edits; because a bulk
  format-converted catalog (e.g. a full `Messier.skylist` with a line per object)
  would dump a pseudo-note onto every object and list notes are not deduped; and
  because the genuinely useful "which of all my lists mention this object?" view is a
  separate, deliberate feature (its own background index, a per-list opt-in, and a
  noise-control story) rather than an implicit consequence of how notes are stored.

## Consequences

- A note from a list opened earlier this session appears on the object even outside
  that list. This is intended (the note is about the object), but can surprise a
  reader who expects notes to be scoped to the list view.
- Notes grow unbounded within a session, but bounded by objects-touched-this-session
  and cheap; restart clears them.
