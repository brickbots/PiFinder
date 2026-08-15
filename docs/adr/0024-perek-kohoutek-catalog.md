# The Perek-Kohoutek catalog is imported from VizieR IV/24, keyed by list position

PiFinder ships the 1510 galactic planetary nebulae of Kohoutek's 2001 revision of the Perek-Kohoutek catalogue as catalog code **PK**. Rows come from VizieR `IV/24/table2`; positions come from SIMBAD or `IV/24/table4`, both J2000; sizes and cross-identifications come from `V/84`. The **Sequence** is the printed catalogue's 1-1510 running number, not the PK designation, which is stored as a name instead.

Status: accepted; implemented 2026-08. Data provenance is recorded in [`astro_data/perek_kohoutek/PROVENANCE.md`](../../astro_data/perek_kohoutek/PROVENANCE.md).

## Context

PiFinder had Abell (79 planetary nebulae) and Sharpless, but no general catalogue of galactic planetary nebulae. Perek-Kohoutek is the standard reference: PK designations are what SIMBAD, star atlases and planetary-nebula observing guides use.

Four facts about the source material drive the decisions below.

1. **The PK designation is not a number.** `PK 036+17.1` encodes galactic longitude, galactic latitude and a running index within that one-degree cell. PiFinder's **Sequence** is an integer, unique within a catalog.
2. **The catalogue holds no photometry.** `IV/24` is deliberately "restricted only to the data belonging to the location and identification of the objects" — no magnitudes, no diameters, no morphological type.
3. **It is fundamentally a B1950 catalogue,** with author-computed J2000 columns on some tables and not others.
4. **Its cross-identification field is a minefield.** 188 of the 1510 entries have a `Name` beginning `M `, and every one of them is **Minkowski**, not Messier.

## Decision

### Source: VizieR IV/24, not the astronomy.com PDF

The request pointed at `astronomy.com/wp-content/uploads/2024/05/Perek-Kohoutek-Catalog.pdf`. That PDF states its own provenance on page 1: it is a typeset reprint of Kohoutek 2001. It carries the same 1510 rows in the same order with the same five fields, but substitutes en-dashes for hyphens in designations and drops the PN G designation, the flags and the notes. So the PDF is not parsed; `IV/24/table2` is taken instead.

Rejected alternatives: `V/84` alone (Strasbourg-ESO, 1992 — richer in physics but keyed on PN G with PK only as a secondary column); `V/127A` (MASH — a different, newer survey that assigns no PK designations); `V/34` (does not exist); `V/42` (Svechnikov & Bessonova close double stars, unrelated).

`V/84` is still used, joined on the PN G designation, for the things `IV/24` lacks: apparent sizes (1034 of 1510 entries) and the `Idents` cross-identification string.

### Sequence: the printed 1-1510 running number

Encoding the PK designation into an integer — say `lll * 100000 + (bb + 90) * 1000 + n` — was rejected. It yields 8-digit sequences, which makes the **Designator** unreadable on a 128-pixel display and keypad entry impractical.

Instead the **Sequence** is the row's position in `table2`, which is ordered by right ascension and is exactly the "Catalog number" column the printed catalogue prints. The real designation goes into `names`, in both spellings PK is written (`PK 036+17.1` and `PK 036+17 1`), so **Text search** and **T9 search** find either.

The consequence is that the auto-generated name `PK 743` is a position in the list, not a designation. This is accepted: WDS and Harris have the same property, and here the numbering at least matches a published one. It is called out in the catalog description and in the user documentation.

### Epoch: J2000 columns only, no precession

No precession runs in this loader. `calc_utils.b1950_to_j2000` is not called and the B1950 columns are never read. Positions are taken from the first source that agrees with the catalogue's own coarse position:

1. **SIMBAD ICRS**, for entries SIMBAD also classifies as a planetary nebula — 1399 of 1510.
2. **`IV/24/table4`**, whose `RAJ2000`/`DEJ2000` columns are author-computed from each row's own equinox — the remaining 111.
3. **`IV/24/table2`**'s own J2000 columns, rounded to 0.1 minute of right ascension and 1 arcminute of declination, as the anchor and last resort.

The agreement check is not ceremonial. Measured against the anchor, SIMBAD and table4 agree to a median of 0.04 arcminutes, and table4 agrees with table2 to a median of 0.56 arcminutes — consistent with table2's rounding and confirming no B1950 leakage. One row fails it: `table4`'s equinox-2000 row for PK 027-03.2 (Vy 1-4) reads declination `-02 26` where its five sibling rows and SIMBAD all read `-06 26`, a four-degree typo in the source. A 5-arcminute agreement tolerance rejects it, and the same guard would catch a SIMBAD identifier resolving to the wrong object. A rejected candidate costs precision, never correctness, because the fallback is the catalogue's own position.

### Magnitude: left empty, and that is the useful behaviour

No PK source carries an integrated nebular magnitude, so every entry is built with an empty `MagnitudeObject`.

This composes correctly with the existing import machinery rather than fighting it. `NewCatalogObject.insert()` skips `insert_object()` when `find_object_id()` matches, so the 211 PK entries that resolve to an existing NGC, IC, Messier, Abell or Sharpless **sky object** keep that object's real magnitude and size. The rest fall back to `UNKNOWN_MAG` and drop out of any magnitude filter on their own. No arbitrary brightness cutoff had to be invented, and no source data is overwritten.

Roughly 200 to 300 of these nebulae are within reach of a small telescope. A metre-class instrument under dark sky with an OIII filter plausibly reaches 600 to 800. The remainder are radio- or infrared-discovered nebulae in the galactic plane, heavily reddened or of very low surface brightness, and are not visually reachable at any aperture. None of that is derivable from the source data, so none of it is encoded as a filter.

### Alias matching: fixed in the shared util, not in this loader

`ObjectFinder.get_object_id()` resolved aliases through `ui_utils.normalize()`, which strips spaces **and hyphens**. Any designation with a compound numeric part therefore collapsed into a plausible but wrong sequence number. Checked against the shipped database, feeding it `table2`'s `Name` column produced **147 matches, of which 145 are false**:

| Alias | `normalize()` | Bound to |
| --- | --- | --- |
| `M 1-1`, `M 2-9`, `M 3-1` (Minkowski) | `m11`, `m29`, `m31` | Messier 11, 29, 31 |
| `H 1-1`, `H 3-29` (Haro) | `h11`, `h329` | Herschel 400 #11, #329 |
| `NGC 650-1` (M76) | `ngc6501` | NGC 6501 |
| `Sh 2-176` | `sh2176` | Sharpless 176 — correct |

Left alone, 145 planetary nebulae would have been silently merged onto Messier open clusters, galaxies and Herschel objects, and displayed those objects' positions and magnitudes.

The fix went into `catalog_imports/catalog_import_utils.py`, where every loader benefits, rather than into a PK-local normaliser:

- `CATALOG_CODE_ALIASES` maps a designation prefix to a PiFinder catalog code, explicitly and by allowlist. It covers the several spellings sources use for the same catalog, including SIMBAD's `PN A66 nn` for Abell planetaries and `Sh 2-nnn` for Sharpless.
- `parse_designation()` splits a designation into prefix and trailing integer, then requires the prefix to be in that allowlist. `M 1-92` leaves prefix `m1`, `H 3-29` leaves `h3`, `NGC 650-1` leaves `ngc650` — none is a catalog, so all are rejected. `Sh 2-176` leaves `sh2`, which is, so it still resolves.
- `ObjectFinder.get_object_id()` uses that path instead of the blunt `normalize()` fallback, so a compound designation can no longer reach hyphen-stripping at all.

A bare `h` is deliberately absent from the allowlist. Herschel 400 uses catalog code `H`, but a bare `H 12` is as likely to mean Hubble or Haro.

Adding `cr` -> `Col` to the allowlist also made an intent already present in `post_processing.add_missing_messier_objects` finally work. It lists `"Cr 42"` among M45's aka names precisely so the Pleiades resolve to one sky object, but `Cr` had never been mapped to `Col`, so the database shipped **two** Pleiades objects. They are now one, with the M 45 and Col 42 listings sharing it.

`NGC 650-1` is the one designation naming two catalog entries. Expanding it is loader knowledge, not util knowledge, so `pk_loader._ngc_pair()` does it — and correctly: the digits after the hyphen replace the tail of the first number, so `650-1` means NGC 650 and NGC 651, not NGC 650 and NGC 1.

### Three data errors this import exposed

PK carries its own positions, so every cross-link is also a check on the catalog it links to. Of the 211 linked entries, 6 disagreed with the PK position by more than 5 arcminutes, and each traced to a real defect. All three are fixed here.

1. **`load_sharpless` never precessed declination.** It computed `j_dec_deg` from `b1950_to_j2000()` and then passed the unconverted `dec_deg`, so only right ascension was precessed. All 313 Sharpless objects sat 0.26 to 0.37 degrees off in declination — exactly the 1950-to-2000 shift. Four linked PK entries made it visible.
2. **`abell.tsv` row 47 had its declination sign dropped.** Abell 47 is at -00 13 51 per SIMBAD and `IV/24`; the file read `+0.2306`. Its constellation, Serpens, spans the celestial equator, so nothing else caught it.
3. **`abell.tsv` row 51 carried the `ngc6742` alias on the wrong row.** NGC 6742 matches row **50** to 0.1 arcminutes and is 66 degrees from row 51; `V/84` independently gives A 50, not A 51, as NGC 6742. The misplaced alias had bound the Abell 51 listing onto NGC 6742's sky object.

After the fixes, 2 of 211 links still disagree — Sh2 176 by 6 arcminutes and Sh2 216 by 17. Both are large diffuse nebulae (Sh2 216 spans roughly 1.6 degrees), where catalogues legitimately place the centre differently. Neither is treated as an error.

The remaining `abell.tsv` aliases were audited positionally against the database: IC 972, NGC 6742, NGC 7076 and IC 1454 all agree within 0.12 arcminutes.

## Consequences

- **211 PK entries share a sky object** with an existing NGC, IC, Messier, Abell or Sharpless listing, inheriting magnitude and size and showing a composed description with both catalog sections. The four Messier links are exactly the four Messier planetary nebulae: M 27, M 57, M 76 and M 97.
- **The util fix changes alias matching for every catalog**, not just PK. Two SAC Multistars listings stopped merging onto a shared object, and M45 started merging with Col 42 as intended. Any catalog whose source data fed compound designations through `ObjectFinder` stops producing false links.
- **Sharpless declinations move by about a third of a degree.** That is a correction, but it changes 313 shipped positions, so it is worth calling out to anyone comparing against an older database.
- **`PK 743` is not a designation.** Anyone reading catalog codes out of the database has to know that the `names` rows, not the sequence, carry the real PK identifier.
- **The vendored snapshot is static.** `astro_data/perek_kohoutek/fetch_sources.sh` regenerates it, but SIMBAD positions drift as astrometry improves, so a future refresh will move some coordinates slightly.
- **A future magnitude source** — HASH, or Frew's planetary-nebula database — could fill in the missing photometry. It would slot in as another join in the loader without touching any of the decisions above.
