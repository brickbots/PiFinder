# Filter freshness: event-driven dirty bumps plus lazy staleness promotion, no timer thread

The filter cache (per-object verdicts and, since PR #526, per-catalog filtered
lists) is keyed on `dirty_time`, which historically advanced **only** when a
filter parameter changed. Two kinds of object state change *under* an unchanged
filter: an object gets **logged** (the observed criterion's input), and object
**altitudes drift** as the sky rotates (≤ 15°/hour). Both left lists wrong until
the user happened to touch a filter parameter.

The decision: keep `mark_dirty()` as the **single invalidation concept**, and
add two freshness triggers that feed it —

1. **Logging is an event**: `Catalogs.mark_logged(obj)` sets `obj.logged` and
   bumps `dirty_time` — but only when an observed criterion is active
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
- **Propagating `logged` to sibling listings of the same sky object**
  (M 31 ≡ NGC 224 share an `object_id`). Rejected — deliberately: logged
  status is **per catalog listing**. `ObservationsDatabase.check_logged` keys
  on `(catalog_code, sequence)`, so build-time flags after a restart mark only
  the listing that was logged. In-session propagation would show sky-object
  semantics that silently revert to per-listing semantics on reboot. If
  sky-object-level observed status is ever wanted, it must start in the DB
  layer (key the observed cache by `object_id`), not in the filter.

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
