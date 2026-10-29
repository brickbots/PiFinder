# Bica et al. (2008), NGC/IC extract

A **supplementary source** for the catalog import: it fills a missing size on
a Magellanic object and never replaces one
([`docs/ax/catalog.md`](../../docs/ax/catalog.md) §9.4). Read by
`fill_bica_sizes` in `python/PiFinder/catalog_imports/supplementary_sources.py`.

Bica E., Bonatto C., Dutra C.M., Santos J.F.C. Jr, *A general catalogue of
extended objects in the Magellanic System*, MNRAS 389, 678–690 (2008),
[2008MNRAS.389..678B](https://ui.adsabs.harvard.edu/abs/2008MNRAS.389..678B).
VizieR catalogue [J/MNRAS/389/678](https://cdsarc.cds.unistra.fr/viz-bin/cat/J/MNRAS/389/678)
(doi:10.26093/cds/vizier.73890678), distributed under the
[VizieR licence](https://cds.unistra.fr/vizier-org/licences_vizier.html).

These files are published data, vendored as fetched: never edit them. To
update, run `fetch.sh` and review the import's log.

## Files

| file | contents |
|---|---|
| `bica2008_ngc_ic.tsv` | the extract: six VizieR ASU-TSV responses, verbatim, one after another |
| `ReadMe` | the catalogue's CDS ReadMe, as released: byte layout, the `Type` codes (Note 1), the name acronyms (Note 2) |
| `fetch.sh` | the recorded queries, which fetch both files again |

## The extract

Fetched 2026-10-24 by `fetch.sh`; each response's `#INFO request=` and
`#INFO request_date=` lines record its URL and time. One query per table and
prefix:

```
https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source=J/MNRAS/389/678/<table>&-out=Names,RAJ2000,DEJ2000,Type,amaj,amin,PA,Com&Names=%3D*<prefix>%5B0-9%5D*&-out.max=unlimited
```

for `<table>` in `table3` (star clusters), `table4` (associations) and
`table5` (emission nebulae), and `<prefix>` in `NGC` and `IC`. The constraint
`Names==*NGC[0-9]*` is VizieR's case-sensitive pattern: the row's names include
an NGC number. VizieR cannot OR two patterns in one constraint, hence two
queries per table. `table6` (HI shells) names no NGC or IC object.

| table | rows naming NGC | rows naming IC | rows naming both | distinct rows |
|---|---|---|---|---|
| `table3` | 257 | 14 | 0 | 271 |
| `table4` | 51 | 0 | 0 | 51 |
| `table5` | 60 | 11 | 5 | 66 |
| | | | | **388** |

The file holds 393 data lines: the five `table5` rows naming both an NGC and
an IC number (NGC1748,IC2114 and four more) come back from both queries, and
the import reads each once. The counts match the released `table3.dat`,
`table4.dat` and `table5.dat` on the CDS FTP site.

Columns, as the ReadMe defines them:

| column | meaning |
|---|---|
| `Names` | the object's names, comma-separated, NGC and IC numbers written `NGC1866`, `IC2105` (32 characters; a longer list continues in `Com` after `&`) |
| `RAJ2000`, `DEJ2000` | J2000 position, to 1 s and 1″ |
| `Type` | class code: `C` cluster, `CN` cluster in nebula, `A` association, `NA` nebula with an embedded association… (Note 1) |
| `amaj`, `amin` | major and minor axis, arcminutes |
| `PA` | position angle of the major axis, degrees; blank when undefined |
| `Com` | comments: membership (`in LMC-N11`), identifications (`not NGC2171`), names overflowing `Names` |

SHA-256 of `bica2008_ngc_ic.tsv` as fetched:
`dd710118268923060c8402af92f29b7eae9b55b7830b65e33b05b9d5d584d444`
(the `request_date` lines change on every fetch; the data lines should not).

## How the import reads it

Each NGC or IC number in `Names` joins the sky object of that catalog listing.
A lettered name (`NGC1921e`, `NGC460nw`, `NGC1850A`) is one member of a pair
or a neighbour, never the number's own object, so it joins nothing; neither
does a name that overflows into `Com` (only `NGC2044W`). A join must pass the
loaders' match guard, a not-found object is skipped, and where two rows reach
one sky object the nearer one fills it. §9.4 has the rule and the reasons.
