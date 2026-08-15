# Perek-Kohoutek source data

Retrieved 2026-08-15 by `fetch_sources.sh` (in this directory). The catalog
build reads these files; it never touches the network.

The decisions behind this import are recorded in
[`docs/adr/0024-perek-kohoutek-catalog.md`](../../docs/adr/0024-perek-kohoutek-catalog.md).

## Files

| File | Source | Rows | Epoch | Used for |
| --- | --- | --- | --- | --- |
| `ReadMe_IV24` | https://cdsarc.cds.unistra.fr/ftp/IV/24/ReadMe | — | — | Byte-position spec for `table2.dat` / `table4.dat` |
| `table2.dat` | https://cdsarc.cds.unistra.fr/ftp/IV/24/table2.dat.gz | 1510 | B1950 **and** J2000 columns | The authoritative row set: PK designation, other name, PN G, coarse J2000 |
| `table4.dat` | https://cdsarc.cds.unistra.fr/ftp/IV/24/table4.dat.gz | 6576 | mixed (`Eq` = 1900/1950/2000) **plus** author-computed J2000 | Arcsecond J2000 positions; several rows per object |
| `ReadMe_V84` | https://cdsarc.cds.unistra.fr/ftp/V/84/ReadMe | — | — | Byte-position spec for `main.dat` / `diam.dat` |
| `main.dat` | https://cdsarc.cds.unistra.fr/ftp/V/84/main.dat.gz | 1143 | B1950 (not read) | `Idents` cross-identifications, `IRAS` name, main designation |
| `diam.dat` | https://cdsarc.cds.unistra.fr/ftp/V/84/diam.dat.gz | 1143 | — | Optical and radio diameters, arcseconds |
| `simbad_pk.tsv` | SIMBAD TAP (query below) | 1967 | ICRS ≈ J2000 | Best available positions |
| `simbad_pk_aliases.tsv` | SIMBAD TAP (query below) | 247 | — | NGC / IC / Messier / Abell / Sharpless cross-IDs |
| `pk.desc` | hand-written | — | — | Catalog description shown in the PiFinder UI |

## Catalogues

**IV/24** — *Catalogue of Galactic Planetary Nebulae*, Kohoutek 2001
(`2001A&A...378..843K`, Abh. Hamburger Sternw. XII). Explicitly "a
continuation of CGPN(1967)", i.e. the direct successor to Perek & Kohoutek
1967. This is the catalogue that assigns PK designations.

**V/84** — *Strasbourg-ESO Catalogue of Galactic Planetary Nebulae*,
Acker et al. 1992. Keyed on PN G rather than PK, but far richer in physical
data. Joined to IV/24 on the PN G designation: 1112 of the 1510 PK rows
match.

## SIMBAD queries

Both are `POST` to `https://simbad.cds.unistra.fr/simbad/sim-tap/sync` with
`REQUEST=doQuery`, `LANG=ADQL`, `FORMAT=tsv`.

Positions (`simbad_pk.tsv`):

```sql
SELECT i.id, b.main_id, b.ra, b.dec, b.otype
FROM ident i JOIN basic b ON i.oidref = b.oid
WHERE i.id LIKE 'PK %'
```

Cross-identifications (`simbad_pk_aliases.tsv`), restricted to the
designation families PiFinder has a catalog for:

```sql
SELECT i1.id AS pk_id, i2.id AS alias
FROM ident i1 JOIN ident i2 ON i1.oidref = i2.oidref
WHERE i1.id LIKE 'PK %'
  AND (i2.id LIKE 'NGC %' OR i2.id LIKE 'IC %' OR i2.id LIKE 'M %'
       OR i2.id LIKE 'PN A66%' OR i2.id LIKE 'SH 2-%')
```

## Cross-check against the published list

Two secondary transcriptions of the same Kohoutek 2001 data circulate among
amateurs, both carrying the identical 1510 rows in the identical order:

- `astronomy.com/wp-content/uploads/2024/05/Perek-Kohoutek-Catalog.pdf`
- a "Perek Kohoutek.xlsx" spreadsheet linked from
  `sites.google.com/view/amateurastronomer/catalogs/nebulae/perek-kohoutek`

Neither is imported. Both drop the PN G designation, the flags and the notes,
both write en-dashes rather than hyphens in designations, and both carry only
the coarse J2000 positions. They are useful as an independent check, and the
spreadsheet was used as one: **all 1510 PK designations and all 1510 "other
designation" values match `table2.dat` exactly.**

The check also found one transcription error in the spreadsheet — row 551
(PK 342-02.1, He 2-198) lost its declination sign, reading `44°13'` where
`table2.dat` reads `-44 13`. That row is 88 degrees out. It is another reason
to take the VizieR original rather than either secondary copy.

## What these sources do not contain

- **No magnitudes.** IV/24 is deliberately restricted to position and
  identification data. V/84 has central-star magnitudes and H-beta fluxes,
  but no integrated nebular magnitude. PK objects that cross-match an
  existing NGC/IC/Abell object inherit that object's magnitude; the rest
  carry `UNKNOWN_MAG`.
- **No morphological type.** Every entry is imported as `PN`.
- **Diameters for 1112 of 1510 only** — the V/84 overlap.

## Designation formats

The same object is written differently in each source. Whitespace inside a
designation is not significant and is collapsed on read.

| Source | PK form | Example cross-ID form |
| --- | --- | --- |
| `table2.dat` / `table4.dat` | `036+17.1` (no prefix, dot before the running number) | `NGC 40`, `A 1`, `Sh 2-176`, `M 1-92` |
| `main.dat` | `171-25 1` (space-separated, space-padded) | `He 2- 231`, `Sa 2-206` |
| SIMBAD | `PK 036+17  1` | `NGC  7008`, `PN A66   80`, `SH 2-176`, `M  76` |

**Trap:** `M 1-92`, `M 2-9`, `M 3-27` and the other 185 `M n-m` entries in
`table2.dat` are **Minkowski**, not Messier. See the ADR.
