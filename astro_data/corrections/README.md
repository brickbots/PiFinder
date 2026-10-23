# Catalog corrections

A **correction** is a cited value that replaces what a source gives, because
the source is wrong for one object. The catalog import applies every
correction in this directory as its final pass, so a correction always has
the last word. It fails the import rather than apply one that no longer fits
the data.

Corrections are the fix of last resort. Before writing one, check that the
fix belongs here and not in one of the other three places
([`docs/ax/catalog.md`](../../docs/ax/catalog.md) §9.2, and
[ADR 0046](../../docs/adr/0046-catalog-corrections-cited-checked-applied-last.md)):

| the cause | the fix |
|---|---|
| a loader misreads its source | fix the loader |
| one better reference covers more than a handful of objects by a stable key | a supplementary source |
| a curated source (EGC, `bright_stars.csv`, `messier_names.dat`) is wrong | edit that file |
| a published source is wrong for one object | **a correction, here** |

If you are about to write more than a handful of corrections citing the same
reference, it is a supplementary source.

## Files

One TOML file per published source, named after it: `steinicke.toml`,
`sac_multistars.toml`, `ngc2000_names.toml`. Each file is also the list of
errors to report to that source's publisher.

**A correction goes in the file of the source whose error it fixes, even when
its key is another catalog's.** NGC 2000.0's names file puts "Horsehead
nebula" on IC 434. Both halves of the fix go in `ngc2000_names.toml`: the
removal keyed `["IC 434"]`, and the name keyed `["B 33"]`.

Files are read in name order, and tables in file order. Other files here,
such as this README, are ignored.

## Tables

Each correction is one table, headed by a **designator**: a catalog code, one
space, and the number, quoted. The code is the one in the database's
`catalogs` table, such as `NGC`, `IC`, `M`, `Sh2`, `SaM` or `WDS`.

```toml
["IC 424"]
why = "Steinicke gives 120'; the nebula is 2.5' across."
sources = ["https://…"]
size = "2.5'"
was.size = "120'"
```

The table's correction applies to the **sky object** that the designator
resolves to, which every catalog listing on it shares, with one exception:
a `description` belongs to that one catalog listing. `["M 42"]` and
`["NGC 1976"]` reach the same sky object, so both may not correct its
magnitude.

Every table needs:

- **`why`**: what is wrong, and what the sources say.
- **`sources`**: a list of citations: a URL where one exists, otherwise a
  full citation (a book and page, or a bibcode).

## Fields

A table can set any of these fields, named like the database columns. Each
field needs **`was.<field>`**, the value it replaces, written the same way.
If the field is empty in the database, write `was.<field> = ""`.

| field | written as | example |
|---|---|---|
| `obj_type` | a type code from `PiFinder/obj_types.py` | `"C+N"` |
| `ra` | sexagesimal hours | `"05 35 17.3"`, `"05:35:17.3"`, `"5h35m17.3s"` |
| `dec` | sexagesimal degrees, signed | `"-05 23 28"`, `"+41°16′09″"`, `"-00 30 00"` |
| `const` | an IAU abbreviation | `"Eri"` |
| `size` | arcminutes, or with a unit: `'`, `"`, `°` | `"2.5'"`, `"60'x30'"`, `"36\""` |
| `mag` | a number, or a list for a variable's range | `11.4`, `[4.86, 7.32]` |
| `description` | text; a multi-line string is fine | `"""…"""` |

- `ra` and `dec` take two or three parts, and only the last may have
  decimals. A bare number is refused, because it could be hours or degrees.
- `size` is read by the loaders' own `parse_arcmin_size`, and must parse
  whole. It corrects the extents. The position angle stays as it was.
- Correcting `ra` or `dec` recomputes the constellation from the new
  position, as a loader would. To overrule that, for a boundary case like
  NGC 1404, correct `const` too.

## Names

```toml
["M 82"]
why = "NGC 2000.0 gives the M 81/M 82 pair's name to M 82 alone."
sources = ["https://…"]
names.remove = ["Bode's nebulae"]
names.preferred = "Cigar Galaxy"
```

- **`names.add`**: a list of names to append.
- **`names.remove`**: a list of names to delete. Every copy goes.
- **`names.preferred`**: one name, placed first among the sky object's names
  so the device and the atlas show it. It is added if the sky object lacks
  it.

Names are compared exactly, including case.

## Identifications

These correct which sky object a designator belongs to.

- **`same_as = "IC 2480"`**: this designator is the same sky object as that
  one. Its listing moves there. If it was the sky object's only listing, the
  whole sky object merges in, names and all, and is deleted. The target's
  values stand and the merged object's are dropped, so correct anything
  worth keeping in the same table.
- **`own_object = true`**: this designator is a sky object of its own. Its
  listing moves to a new sky object that starts as a copy of the old one.
  Correct its fields in the same table, with `was` stating the copied
  values.
- **`hip = 102989`**: this star listing is that Hipparcos star. Use it where
  the source's position is too far off for the star cross-match to find it.

A listing moves with the names that are its designator and come from its
own catalog, such as "IC 5281" from IC. Its other names stay where they
are. If it has no such name, as with an M listing, whose "M nn" name comes
with Steinicke's NGC record, the designator is added as a name where it
lands.

All splits (`own_object`) run before all joins (`same_as`), and both run
before any other correction. So the other fields in an identification's
table, and `was`, apply to the sky object the designator ends up on.

`hip` is the one correction the final pass does not apply. The star
cross-match reads it before it matches, and uses it in place of the
position.

## Checks

The import fails, naming the file and the designator, when:

- a file isn't valid TOML, or a table has an unknown key or a malformed
  value;
- `why` or `sources` is missing;
- a field has no `was.<field>`, or `was` equals the correction;
- a field already holds the corrected value (**redundant**: delete the
  correction);
- a field holds neither `was` nor the correction (**stale**: the data
  underneath has changed, so check the correction against its source);
- a designator resolves to nothing;
- two corrections reach the same field, or the same name, of one sky object;
- two corrections identify the same listing, or both give it a `hip`;
- `names.remove` names a name the sky object doesn't have, `names.add` one it
  already has, or `names.preferred` the name that is already first;
- a `same_as` is already true, or an `own_object` designator is already its
  own sky object;
- a `same_as` points at a designator that has its own `same_as` (point it at
  the final sky object instead);
- a split or join leaves its old sky object still carrying the designator as
  another catalog's name, compared ignoring case and spaces as the loaders'
  matching does. That catalog's listing was matched through the
  wrong identification and would be left behind, so correct it too. If the
  name is only a stray, a `names.remove` on the old sky object clears it.
  That is the usual case for an M listing: Steinicke's NGC record carries
  its "M nn" name, so splitting or moving one needs a `names.remove` of that
  name keyed by the NGC designator, which records that the NGC record's
  cross-identification is wrong.

A check compares values within tolerances: 0.05 for magnitudes, 1″ for RA
and Dec, each taken separately, and 1″ for each size extent once parsed. So
`"120'"` and `"2°"` are the same size.
