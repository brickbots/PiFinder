# Nearby objects: a (Dec, RA) haversine index, queried as a bounded window, with the cursor bound to the pointing

Two features ask the same question — *which catalog objects are near where the
scope points?* The object list's **Nearby** sort wants them ranked, nearest
first; the chart's **nearby-DSO marker layer** wants everything inside the
current field. Both are served by `ClosestObjectsFinder` in
`PiFinder/nearby.py`, and both run against the live pointing while the user
slews.

That last part sets the constraints. The answer must be correct at *any*
declination, not just near the equator where most testing happens. It must be
cheap enough to compute inside the 30 Hz draw loop on a Pi. And it must decide
what the list does when the answer changes under the user's hands.

## Index the sky as `[dec, ra]`, in radians, haversine

The spatial index is a scikit-learn `BallTree` with `metric="haversine"`. That
metric is documented for geographic coordinates: **dimension 0 is latitude,
dimension 1 is longitude**. Declination is the latitude; right ascension is the
longitude. So rows are `[dec_rad, ra_rad]`, and every query point must be built
the same way.

This is written down because the argument order is invisible at the call site —
it is two floats in a list, and the wrong order raises nothing. Worse, the
mistake hides: when two objects share a meridian the metric degenerates to
`|dec1 - dec2|`, which is right whichever way round the axes go. Any test or
spot-check that keeps RA fixed will pass on a swapped index. **Treat a
same-meridian check as no check at all** — exercise this code with objects at
different RAs and at high declination, where a swapped axis order is loudest.

The alternative was to drop the index: compute a vectorised haversine over all
objects and `argsort`. Measured at 0.9 ms (14 000 objects) against the tree's
1.5 ms — no meaningful gain, and it gives up `query_radius`, which is what the
chart layer actually needs (bounded by angular distance, not by count). Keep
the BallTree.

## The Nearby list is a bounded window, not a total ordering

`get_closest_objects` accepts `n=0` meaning "rank everything", and the object
list used to take it. Ranking the whole catalog to draw about nine rows costs
O(N) twice over: once in the k-NN query, and again in the cursor-tracking
helper that rebuilds a `(catalog_code, sequence)` dict over the new ordering in
pure Python.

| N | k = N query | k = 200 query | cursor helper |
|---|-------------|---------------|---------------|
| 14 000 | 1.5 ms | 0.09 ms | 7.6 ms |
| 40 000 | 4.4 ms | 0.13 ms | 22 ms |

(Measured on a fast dev machine; a Pi is roughly an order of magnitude slower,
against a 33 ms frame budget.)

The cost is inherent to producing a *total* ordering — the vectorised
alternative above measured no better. It can only be avoided, so the decision
is to avoid it: `NEAREST_LIST_CAP = 200`, and the object list queries
`k = min(cap, N)`. Everything downstream is then bounded by the cap rather than
by catalog size, which is what keeps the re-rank off the frame budget.

**The trade-off:** a Nearby-sorted list no longer scrolls down to the object on
the far side of the sky. An object 140° away is not "nearby" under any reading,
and paying O(N) on every degree of slew to keep that tail reachable is the
wrong bargain. Catalog and RA sort still expose the full set.

Lazily extending the window as the user scrolls past 200 was considered and
rejected: it buys back an ordering with no observing use, at the cost of
carrying a paging state machine through the re-rank path.

`n=0` stays supported for callers that genuinely want everything, but the cap
is the default posture for anything drawing a list.

### Two lengths, and which one each caller means

Capping makes explicit something the screen already half-had: the list the user
navigates is not the same length as the catalog behind it. (Even before the cap,
`deduplicate_objects` merged listings sharing an `object_id`, so the ranked list
was already the shorter of the two.)

`UITextMenu.get_nr_of_menu_items` counts `_menu_items`, the source list.
`UIObjectList` overrides it to count `_menu_items_sorted`, because **that** is
what the screen draws, scrolls, opens and serialises. Anything addressing a row
— cursor clamping, the scrollbar, opening the focused object, the serialised
selection — must use the length of the list it is indexing, or the cursor can
address rows that do not exist. Long-DOWN to "the end" is the case that finds
this immediately.

The catalog's own object count is a *different* quantity, and it stays the
source length: it is reported in `catalog_info_1` for the header, where the user
is being told how big the catalog is, not how far the carousel scrolls.

Two consequences worth stating, because both were latent and are now reachable:
a sort may legitimately produce an empty list while the source is non-empty, so
the scrollbar must tolerate a zero count; and the in-frame re-rank must not run
before the spatial index has been built for the current list, or it replaces a
populated list with an empty one mid-draw. `Nearby.should_refresh` answers False
until the index is ready, which keeps the explicit `sort()` path the only thing
that can empty the list.

## Staleness is measured on the sky, not per axis

The ranking is recomputed when the pointing has moved far enough to change it.
"Far enough" is a **great-circle separation** from the pointing the current
ranking was built at (`great_circle_degrees`), compared against
`MAX_DEVIATION = 1.0` true degrees.

Per-axis RA/Dec degrees are not a usable proxy for this, and the reason is
worth recording because the cheaper test looks reasonable:

* One degree of RA spans `cos(dec)` degrees on the sky — 0.17° at Dec 80°,
  0.017° at Dec 89°. A per-axis threshold therefore re-ranks for movement the
  user cannot see, and does so exactly where slewing is slowest and a stall is
  most visible.
* RA wraps. A test on raw difference reads the step from 359.5° to 0.5° as 359,
  so it fires continuously in a band around the meridian.

Neither failure loses a refresh, so neither is visible as wrong output — they
are pure cost, which is why a per-axis test can sit unnoticed. The great-circle
form has no such blind spot and costs one `arccos`.

A second trigger re-ranks after `MAX_TIME = 10` s regardless of pointing. Its
job is *not* pointing changes — the deviation test owns those. It exists to pick
up catalog and filter changes and altitude drift. Sized from the sky's 15°/hour:
10 s bounds the drift error to ~0.04°, far inside anything the list expresses.
A shorter cadence buys nothing and re-ranks a stationary scope for no reason.

## The top row follows the pointing; a scrolled cursor follows the object

A Nearby list is rebuilt for two different reasons, and the user's intent
differs between them.

A **filter-driven** rebuild — the user logged an object, or tightened the
magnitude or altitude filter — should hold the cursor on the selected object, or
on the first of its old successors that survived. That is the natural next
target, and it is what `_next_target_index` exists for (see the filter-freshness
ADR).

A **pointing-driven** re-rank is the opposite case. The user slewed the scope
*in order to change what is nearest*. Carrying the cursor along with the
previously selected object works directly against that: the focused row drifts
down the ranking, away from what they just pointed at.

The decision splits the two:

* While the cursor sits on the top row, a pointing-driven re-rank keeps it
  there. The focused object is the nearest object, which is what the mode is
  for.
* Once the user scrolls off the top they are browsing, and the cursor pins to
  their selected object as it migrates through the ranking. Scrolling back to
  the top re-arms the tracking.
* Filter-driven rebuilds keep the pinning behaviour unconditionally.

This needs no new state and no user-facing setting: "the user has not scrolled"
is exactly `_current_item_index == 0`, read before the list is replaced.
Rejected alternatives: always reset to the top (destroys browsing — the list
becomes unusable as anything but a readout), and always pin to the object
(the behaviour this replaces).

## One rebuild policy for the spatial index

The tree is rebuilt only when the object set behind it changes, guarded on the
catalog filter's `dirty_time` — the same key `UIChart` already uses for its own
nearby-marker index. `dirty_time` does not cover a list rebuilt from source, so
`refresh_object_list` invalidates the index explicitly. Two consumers, one
policy, so a filter edit cannot leave the list and the chart disagreeing about
what is on the sky.

## Consequences

* Correctness no longer depends on where the scope is pointed. The chart layer
  gains more from this than the list does: a marker that is silently absent from
  the field is not something the user can notice.
* Per-refresh work is bounded by `NEAREST_LIST_CAP` rather than catalog size,
  which is what allows the re-rank to stay on the draw path at all.
* Nearby lists are truncated to 200 objects — the one behaviour a user may
  experience as a loss.
* Sort orders must each be given a branch in `sort()` *and* an entry in
  `_sort_order_label`. Both labels route through that one helper so a mode
  cannot be displayed under another mode's name.
