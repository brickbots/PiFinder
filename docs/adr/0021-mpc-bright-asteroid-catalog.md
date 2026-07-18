# MPC annual bright-minor-planet files for the asteroid catalog

PiFinder needs an asteroid subset small enough for a Raspberry Pi and useful to
visual observers. The complete MPCORB catalog is orders of magnitude larger
than the set that can become visually observable in a given year. An absolute
magnitude (`H`) cut is also insufficient: it can omit intrinsically faint
near-Earth asteroids during a bright close apparition.

The `MP` dynamic catalog uses the Minor Planet Center's annual
`Ephemerides/Bright/<year>/Soft00Bright.txt` file. It is already curated by
observing year, uses the standard MPCORB one-line format supported by the
pinned Skyfield release, contains numbered asteroids, and supplies the `H` and
`G` photometric parameters.

## Decisions

- Load the current year's file and opportunistically merge next year's once it
  is published. A previous-year file remains a stale-data fallback around New
  Year or during network failure. Duplicate asteroid numbers use the newest
  packed element epoch. Because a Pi 4 has no RTC, source-year selection waits
  for trustworthy GPS time; before that, the UI may identify an already stored
  edition from its filename but never chooses a download year from wall time.
- The minor-planet number is the catalog sequence. Observation logs for virtual
  objects are keyed by `(catalog, sequence)`, so `MP 4` must remain Vesta across
  refreshes and restarts.
- Propagate the small element set locally in vectorized NumPy operations and
  compute apparent magnitude with the IAU H-G phase law. Non-finite values and
  objects fainter than the named magnitude-15 catalog safety limit are omitted;
  the user's ordinary magnitude and altitude filters remain the observing
  controls.
- For visible objects, search 550 days for the first upcoming
  ecliptic-longitude opposition (or greatest elongation for an interior object)
  and the peak magnitude associated with that apparition. Day zero is excluded
  from “upcoming” so an event that just passed is not reported as the next one.
- Catalog source updates are transactional: bytes go to a temporary sibling,
  are parsed and validated, and atomically replace the active file. The old
  objects and their source edition remain visible during download or after failure.
  A populated catalog shows a compact determinate or indeterminate progress bar.
- JPL SBDB is a documented replacement candidate if MPC retires the annual
  file, not an automatic fallback. Supporting two unrelated runtime formats
  would add failure modes without improving normal operation.
- Existing persisted Catalog and Type filters receive `MP` and `AS` through a
  one-time config migration. Its marker ensures a later user choice to disable
  asteroids remains authoritative.

## Consequences

Asteroid calculations stay bounded to a few hundred source rows, stable numbers
make jump-to and logging meaningful, and close NEO apparitions are retained
without downloading the full MPCORB database. Annual elements are two-body
propagated, so they do not claim Horizons-level precision; vectorized results
are regression-tested against Skyfield's per-object MPCORB orbit builder.
