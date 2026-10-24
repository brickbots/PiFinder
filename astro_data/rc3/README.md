# RC3, extract of the V-coded BT rows

A **supplementary source** for the catalog import: where Steinicke's Bmag is
one of these values, Steinicke read a V-band magnitude as B, and his V is one
colour too bright; the import replaces that V with his Bmag
([`docs/ax/catalog.md`](../../docs/ax/catalog.md) §9.4). Read by
`replace_rc3_v_magnitudes` in
`python/PiFinder/catalog_imports/supplementary_sources.py`.

de Vaucouleurs G., de Vaucouleurs A., Corwin H.G., Buta R.J., Paturel G.,
Fouqué P., *Third Reference Catalogue of Bright Galaxies* (RC3),
Springer-Verlag, New York (1991). VizieR catalogue
[VII/155](https://cdsarc.cds.unistra.fr/viz-bin/cat/VII/155), the revised
version Corwin submitted. The `ReadMe` here carries the authors' notice, which
asks that copies of RC3 travel with that documentation.

These files are published data, vendored as fetched: never edit them. To
update, run `fetch.sh` and review the import's log.

## Files

| file | contents |
|---|---|
| `rc3_bt_code_v.tsv` | the extract: one VizieR ASU-TSV response, verbatim |
| `ReadMe` | the catalogue's CDS ReadMe, as released |
| `fetch.sh` | the recorded query, which fetches both files again |

## The extract

Fetched 2026-10-24 by `fetch.sh`; the response's `#INFO request=` and
`#INFO request_date=` lines record its URL and time:

```
https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source=VII/155/rc3&-out=name,altname,PGC,RA2000,DE2000,BT,BT_code,e_BT&BT_code=%3D%3DV&-out.max=unlimited
```

The ReadMe's note on `BT_code`: `"V" = BT is a V-band magnitude rather than a
B-band magnitude`. The constraint `BT_code===V` is VizieR's strict equality; a
plain `BT_code=V` is caseless and also returns the twelve rows coded `v`, "the
nucleus of the galaxy is variable".

**145 rows**, all coded `V`, as many as the released `rc3.gz` holds; 101 of
them name an NGC or IC galaxy.

| column | meaning |
|---|---|
| `name` | NGC or IC designation (`NGC    78A`), or blank |
| `altname` | UGC, ESO, MCG, UGCA or CGCG designation |
| `PGC` | PGC number |
| `RA2000`, `DE2000` | position, equinox 2000 |
| `BT` | total magnitude, here a V-band one |
| `BT_code` | `V` |
| `e_BT` | mean error on `BT` |

SHA-256 of `rc3_bt_code_v.tsv` as fetched:
`a5db2bf9ffa087ae5f0d77ef2a135472df986d438cd9b93d221a5a0f24c984b6`
(the `request_date` line changes on every fetch; the data lines should not).

## How the import reads it

Each NGC or IC `name` is joined, letter included, to the Steinicke row the
Steinicke loader keeps for that number: `NGC 78A` is the row PiFinder lists as
NGC 78. Where that row's Bmag equals `BT` within 0.05 and the sky object still
holds that row's V, the V becomes the Bmag. §9.4 has the rule and the reasons.
