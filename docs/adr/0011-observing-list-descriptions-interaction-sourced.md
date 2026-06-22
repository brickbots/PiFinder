# Observing list descriptions are interaction-sourced, not scanned from disk

An **observing list description** is the per-target description an observing list
carries — the observing-list counterpart of a catalog description (see the Catalog
[CONTEXT.md](../ax/catalog/CONTEXT.md)). We attach them **at list-load time**: when
the user opens an observing list, `read_list` records that list's description onto
every **resolved** object it contains, stored in `CompositeObject.list_descriptions`
keyed by the list name. Because the resolved object is the shared catalog instance,
these **accumulate for the session** across every list opened and surface wherever
the object is later viewed — including when it is reached by browsing its catalog
directly rather than through the list. They are not persisted (gone on restart) and
there is no removal path within a session. Coordinate objects carry none; their list
text becomes their own description, as they have nothing else.

## Considered options

- **Interaction-sourced (chosen)** — descriptions come only from lists the user
  actually opens this session. Zero cost beyond reading lists the user wanted anyway,
  and the cross-list aggregation ("this object is on several of my lists") falls out
  for free as opened lists accumulate on the shared object.
- **Data-sourced (rejected)** — scan every list file on disk so an object carries
  descriptions from any list mentioning it, with no interaction. Rejected because it
  needs a background indexer plus a cache invalidated on file edits; because a bulk
  format-converted catalog (e.g. a full `Messier.skylist` with a line per object)
  would dump a pseudo-description onto every object and observing list descriptions
  are not deduped; and because the genuinely useful "which of all my lists mention
  this object?" view is a separate, deliberate feature (its own background index, a
  per-list opt-in, and a noise-control story) rather than an implicit consequence of
  how descriptions are stored.

## Consequences

- A description from a list opened earlier this session appears on the object even
  outside that list. This is intended (it is about the object), but can surprise a
  reader who expects it to be scoped to the list view.
- They grow unbounded within a session, but bounded by objects-touched-this-session
  and cheap; restart clears them.
