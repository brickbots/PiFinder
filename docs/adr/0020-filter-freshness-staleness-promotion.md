# Filter freshness and observed identity: event-driven dirty bumps, lazy staleness promotion, object_id-derived observed status

The filter cache (per-object verdicts and, since PR #526, per-catalog filtered
lists) is keyed on `dirty_time`, which historically advanced **only** when a
filter parameter changed. Two kinds of object state change *under* an unchanged
filter: an object gets **logged** (the observed criterion's input), and object
**altitudes drift** as the sky rotates (≤ 15°/hour). Both left lists wrong until
the user happened to touch a filter parameter.

The decision: keep `mark_dirty()` as the **single invalidation concept**, and
add two freshness triggers that feed it —

1. **Logging is an event**: `Catalogs.mark_logged(obj)` sets `obj.logged` —
   on the object and on every sibling composite sharing its non-negative
   `object_id` (see *Observed status is a sky-object property* below) — and
   bumps `dirty_time`, but only when an observed criterion is active
   (`observed != "Any"`), since otherwise no verdict can change and the ~0.58 s
   full re-scan would be wasted.
2. **Altitude staleness is a lazily-evaluated condition**:
   `CatalogFilter.is_stale()` reports verdicts outdated by time — altitude
   criterion active *and* alt/az available *and* (verdicts older than
   `ALTITUDE_STALE_SECONDS = 600` *or* the alt/az fix arrived after verdicts
   were computed without one). Staleness never invalidates by itself;
   `Catalogs.filter_catalogs()` — the single "filter everything" entry point —
   **promotes** it to a `mark_dirty()` so *both* cache layers re-evaluate.
   `is_dirty()` surfaces staleness too, so the non-forced UI refresh paths
   (screen activation) notice it, and `UIObjectList.update()` checks
   `is_stale()` each frame so a list screen left open all night refreshes in
   place — the same pattern as `Nearby.should_refresh()`.

## Sizing the TTL

Altitude drifts at most 15°/hour, so a 600 s cadence bounds the error to
~2.5° — well inside the 10°-step granularity the altitude filter is set in.
No user-visible setting: a good fixed default beats a config knob nobody can
reason about.

## Observed status is a sky-object property

*(Amended 2026-07-10 — this supersedes the first version of this ADR, which
kept logged status per catalog listing.)*

**Log entries** stay recorded per listing: `obs_objects` keys on
`(catalog, sequence)`, exactly as the user logged it — no schema change, no
migration. **Observed status** is derived per sky object on top of that:
when `ObservationsDatabase` loads its observed cache, each logged listing is
mapped to its `object_id` through the objects DB (a separate sqlite file;
the mapping is done Python-side — obs rows are few), and
`check_logged(obj)` tests a DB-backed object (`object_id >= 0`) by id
membership. Logging M 31 therefore marks NGC 224 observed — in the current
session (via `mark_logged` propagation), after a restart (re-derived at
cache load), and **retroactively** for every historical observation.

The **virtual-id fallback is load-bearing**: `CompositeObject.object_id`
defaults to `-1`, and the `VirtualIDManager` mints session-only negative ids
for planets, comets, and coordinate objects — ids that are *not stable
across restarts*. Keying those by id would either cross-mark everything
sharing the default or silently lose status on reboot (logging Mars must
not mark Jupiter), so negative-id objects keep the `(catalog, sequence)`
test. Listings that no longer resolve to an object id (removed catalogs)
also stay listing-keyed.

The details screen follows the same identity: `get_logs_for_object`
resolves a DB-backed object's sibling listings and returns log entries
recorded under any of them, so NGC 224's details show M 31's logs ("1
Logs") instead of contradicting the checkmark.

Durability options considered:

- **In-memory-only propagation** (mark siblings in `mark_logged`, derive
  nothing at load). Rejected: sky-object semantics that silently revert to
  per-listing semantics on restart — the exact inconsistency the first
  version of this ADR rejected propagation to avoid.
- **Schema migration adding `object_id` to `obs_objects`.** Rejected: it
  stores derivable data, needs a backfill for every user's observations DB,
  and would still need the listing fallback for virtual objects.

## Considered options

- **Periodic `mark_dirty()` from the UI loop** (a timer that bumps the filter
  every N minutes while an altitude criterion is active). Rejected: it re-scans
  even when nothing will read the result (no list on screen, next list open is
  hours away), and it spreads the freshness rule across the UI layer. Lazy
  promotion pays the scan exactly when a consumer asks for filtered objects.
- **Background timer thread.** Rejected: thread-safety cost (the filter and
  catalogs are touched from the UI thread and the catalog loader thread
  already) for no UX gain over lazy promotion — a list nobody is looking at
  doesn't need fresh verdicts.
- **TTL check inside `Catalog.filter_objects()` only.** Rejected: defeating the
  per-catalog guard is not enough — the per-object layer would still return
  cached verdicts (`obj.last_filtered_time > dirty_time`), so the re-scan would
  recompute nothing. Any freshness trigger must advance `dirty_time` itself;
  hence promotion lives in `filter_catalogs()`, above both layers.
- **Per-object invalidation on logging** (touch only the logged object's cached
  verdict). Rejected as over-engineering: log events are rare (the user just
  spent minutes observing), so one full re-scan per log is cheap; and the
  catalog-layer lists would still need selective invalidation for every catalog
  containing the object.
- **Keeping logged status per catalog listing** (the first version of this
  ADR). Superseded: the checkmark, the observed filter, and the details
  screen all present observed-ness as a fact about the sky object, and
  per-listing status made them contradict each other (M 31 observed,
  NGC 224 "Not Logged"). The replacement starts in the DB layer — the
  observed cache is keyed by `object_id` — with in-session `mark_logged`
  propagation matching what the DB derives after a restart. See *Observed
  status is a sky-object property* above.

## Consequences

- The no-altitude-criterion case never pays: `is_stale()` short-circuits on
  `altitude == -1`, preserving PR #526's O(catalogs) list-open fast path.
- With an altitude criterion but no GPS lock, `is_stale()` stays False (alt/az
  can't improve the verdicts), so there is no futile re-scan loop before a fix;
  the lock's *arrival* is what triggers the one re-filter. This also closes the
  boot-time gap where pre-lock verdicts skipped the altitude test entirely and
  everything "passed" forever.
- Planet positions mutated in place every ~5 min get re-judged on the same
  cadence whenever an altitude criterion is active; without one, a planet's
  drifting constellation assignment can still go stale against a constellation
  criterion — a pre-existing, cosmetically small gap left open.
- A list screen left open takes the ~0.58 s re-scan hiccup once per TTL. Judged
  acceptable against silently wrong lists.
- List refreshes keep the cursor on the selected object; if it was filtered
  out (just logged, or set below the altitude criterion), the cursor falls to
  the object that *followed it in the old order* — the natural next target —
  instead of resetting to the top (`_next_target_index` in
  `ui/object_list.py`; matching is by `(catalog_code, sequence)` because
  `CompositeObject.__eq__` compares `object_id` alone and would land on a
  sibling listing).
- Observed identity is **retroactive**: every historical observation marks its
  sibling listings observed the moment this ships — an "Observed: No" NGC list
  may visibly shrink after upgrade, sibling rows gain the checkmark, and a
  sibling's details show the combined log count.
- The freshness clock is wall-clock (`time.time()`), inherited from the
  existing cache timestamps. A backward clock step (PiFinder sets time from
  GPS; no RTC) can leave `last_filtered*` in the future so `mark_dirty()` never
  wins until restart — a pre-existing hazard this ADR does not fix. The known
  remedy is a monotonic **generation counter** (int incremented by
  `mark_dirty`, compared for equality), which would also fix the
  loader-thread/UI-thread stamp race and the pickle-cache carrying stale
  verdict timestamps across sessions. Deferred as follow-up work.
- Companion glossary: [`docs/ax/catalog/CONTEXT.md`](../ax/catalog/CONTEXT.md)
  (Dirty time, Stale).
