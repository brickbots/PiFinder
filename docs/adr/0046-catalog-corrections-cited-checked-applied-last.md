# Catalog errors are fixed in one of three places; source errors become cited, checked corrections applied last

**Status: accepted** (2026-10-22). Vocabulary: [`docs/ax/catalog/CONTEXT.md`](../ax/catalog/CONTEXT.md), *Import*. Architecture: [`docs/ax/catalog.md`](../ax/catalog.md) §9.

An audit of `objects.db` against OpenNGC and Hipparcos (paperChart_dev, 2026-10) found about 400 wrong values: types, names, positions, magnitudes, sizes. Most come from **loaders** misreading their **sources**. A substantial minority come from the sources themselves — Steinicke's 120′ for IC 424, SAC's "Beid" for Keid, NGC 2000.0's "Bode's nebulae" on M 82 — which a loader reads faithfully and must not "fix" by guessing. PiFinder had no place for a value that contradicts its source: the only precedent was `extra_names.dat`, three lines no loader reads.

## Decision

1. **Every wrong value is fixed in exactly one of three places.**
   - The loader misreads its source → **fix the loader**.
   - A published source is wrong, and one better reference covers more than a handful of objects by a stable key → **a supplementary source**: a vendored reference joined on that key (Hipparcos and IAU WGSN by HIP, Bica et al. 2008 by designation), which fills or replaces one field by rule and never adds listings.
   - A published source is wrong for one object, and no rule or reference can produce the value → **a correction**.

   A **curated source** — a list PiFinder compiles itself, such as EGC or the bright stars — is none of these: it is edited directly.

2. **A correction is keyed by a designator** (`"NGC 604"`) and applies to the sky object that designator resolves to; a description correction applies to that one catalog listing. `objects.id` is an autoincrement and changes on every rebuild, so it cannot be the key. Two corrections that reach the same field of one sky object through different designators (M 42, NGC 1976) fail the build, as does a designator that resolves to nothing.

3. **A correction does one of three things:** set fields (`obj_type`, `ra`, `dec`, `const`, `size`, `mag`, `description`); edit names (`names.add`, `names.remove`, and `names.preferred`, which puts a name first); or correct an **identification** — in either direction (`same_as = "IC 2480"`, or `own_object = true` to detach a designator into a sky object of its own), or, for a star listing, by naming its Hipparcos number (`hip = 102989`). It never creates a sky object from nothing or deletes a listing: every orphan and duplicate the audit found is a loader bug.

4. **Corrections are applied in one final pass**, after every loader, the star cross-match, the supplementary sources and type normalisation, and before image resolution and the database is finalised. A correction therefore always has the last word, and its type is checked against the normalised type codes. A split (`own_object`) fails the build if the sky object it splits still carries another catalog's name equal to the detached designator, since that listing was matched through the wrong identification and the split would leave it behind.

   **The one exception is `hip`.** Stars are identified by cross-matching each listing's position to Hipparcos, and a source position whole degrees off (SAC's α Mic and ξ Lup) finds no match — so a position corrected in the final pass would come too late to merge the star or to let Hipparcos supply its values. The star-identity stage therefore reads `hip` corrections before it cross-matches, and uses them in place of position. An identification feeds matching; every other correction overwrites a value, and those stay last. A `hip` correction is redundant if the cross-match alone finds that number.

5. **The format is TOML**: one table per designator, one file per corrected source, under `astro_data/corrections/` (`steinicke.toml`, `sac_multistars.toml`, `ngc2000_names.toml`…). Field names are the database's columns; values are in the units references publish — sexagesimal RA and Dec, sizes through the loaders' own `parse_arcmin_size`, a magnitude as a number or a variable's range as a list. `why` and `sources` (URLs) are required.

6. **Every field correction states the value it replaces** (`was.size = "120'"`), and the pass checks it, within tolerances (0.05 mag, 1″, sizes compared parsed). If the field already holds the corrected value, the correction is redundant; if it holds anything other than `was`, the correction is stale. Both fail the build. Name and identification operations carry the same check implicitly: a `names.remove` of an absent name, or a `same_as` on designators already one sky object, fails.

## Considered options

- **Edit the published source files.** Rejected: a vendored source would no longer be what its publisher released, an updated release could not be dropped in, and nothing would record what was changed or why. Curated sources are the exception because PiFinder is their publisher.
- **Special-case objects in loader code.** Rejected: values without citations, scattered across thirteen loaders, invisible to anyone reviewing the data. `add_missing_messier_objects` is the existing example of the pattern, and is left as it is rather than extended.
- **Corrections for the systematic errors too** — copy Bica's 49 Magellanic sizes and WGSN's names in by hand. Rejected: hundreds of transcribed rows that drift from their reference and cannot be regenerated. That is what a supplementary source is for.
- **Apply corrections at insert time, as each loader writes.** Rejected: a later loader's fill or a supplementary source's replacement would land on top, and a correction would no longer have the last word.
- **Build the whole catalog in memory, correct it, write once.** The cleanest reading of "correct before it reaches the DB", but it rewrites every loader. The database being built is a scratch file until it is finalised, so a final pass gives the same guarantee — the shipped file never holds an uncorrected value — for a fraction of the change.
- **Key by `object_id` or by position.** `object_id` is unstable across rebuilds; positions are ambiguous, since the audit found 582 groups of NGC/IC objects at identical coordinates.
- **YAML, TSV, JSON Lines.** YAML 1.1 reads `13:42:47` as a base-60 integer — a trap for RA. TSV cannot express name edits or identifications. JSON has no comments, and hand-editing it is error-prone. TOML has comments and multi-line strings, diffs cleanly, and matches paperChart's `labels.toml`.
- **Warn on stale or redundant corrections instead of failing.** Rejected: the import runs on a developer's machine, where a failure costs a minute, and a warning in a long import log is a warning nobody reads.

## Consequences

- **Corrections are written last, after the loader fixes.** Those fixes change what some designators resolve to and what values sit underneath — attaching Steinicke's duplicates to their twins moves `NGC 2239` onto `NGC 2244`'s sky object — and the `was` check reports exactly which corrections they disturbed.
- **Re-vendoring a source fails the import until its corrections are reviewed.** That is the point: a correction Steinicke has since fixed should be deleted, not silently re-applied over the fix.
- **Each corrections file is the upstream report for its publisher.** `sac_multistars.toml` is the list to send SAC.
- **Unresolved identifications stay as the sources give them.** A correction needs a decided value and a citation; NGC 6002, NGC 3355 and the other rows the audit could not settle have neither.
- **Name order carries meaning**, because `names.preferred` and the WGSN names work by placing a name first. The import must therefore keep names in a reproducible order; a `set()` of names follows Python's per-process hash seed and does not.
- **The import gains a development dependency**: `tomli` on Python 3.9, `tomllib` from 3.11. The device never runs the import.
