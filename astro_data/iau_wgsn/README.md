# IAU Catalog of Star Names (WGSN)

A **supplementary source** for the catalog import: joined by Hipparcos
number, it adds each star's IAU name as its **preferred name**, and the older
names stay as ordinary names ([`docs/ax/catalog.md`](../../docs/ax/catalog.md)
§9.4). Read by `add_wgsn_names` in
`python/PiFinder/catalog_imports/supplementary_sources.py`.

The IAU Catalog of Star Names (IAU-CSN) is kept by the IAU Division C Working
Group on Star Names (WGSN), which publishes it on its own site as a living
table: <https://exopla.net/star-names/modern-iau-star-names/>. The IAU's
former page (`https://www.iau.org/public/themes/naming_stars/`) no longer
exists, and the WGSN's fixed-width `IAU-CSN.txt` was last updated 2022-04-04,
before about 200 of the names below were adopted. IAU products are released
under Creative Commons Attribution.

These files are published data, vendored as fetched: never edit them. To
update, run `fetch.sh` and review the import's log.

## Files

| file | contents |
|---|---|
| `modern-iau-star-names.html` | the WGSN's page, verbatim, as `fetch.sh` fetched it |
| `iau_csn.tsv` | the catalog table, extracted from the page by `extract.py`; what the import reads |
| `extract.py` | the extraction: Python 3 standard library only, so the import never parses HTML |
| `fetch.sh` | fetches the page again and runs `extract.py` |

## The extract

Fetched 2026-11-09 03:36 UTC from
`https://exopla.net/star-names/modern-iau-star-names/`. The table holds
**652 names**, the latest adopted 2026-10-15:

- 579 give a Hipparcos number, naming 578 stars: HIP 72105 carries two names,
  Izar and Pulcherrima, with no component to tell them apart;
- 73 give none: mostly exoplanet hosts (WASP-, HAT-P-, XO-) and other objects
  Hipparcos does not list (pulsars, protostars), and Mesarthim, which the
  table now gives as `* gam Ari`, the pair, where the 2022 `IAU-CSN.txt`
  gave HIP 8832.

`iau_csn.tsv` keeps the page's rows in its order, and these of its columns,
each cell's text with its HTML entities decoded:

| column | the page's header | meaning |
|---|---|---|
| `name` | proper names | the IAU name, in the WGSN's spelling (diacritics kept: Mönch, Dhanuśarāgra) |
| `wgsn_id` | NEC+ | the WGSN's own catalog number |
| `designation` | Designation | HR, HD or another designation (`HR 6555`, `WASP-121`) |
| `hip` | HIP | the Hipparcos number; blank for none |
| `bayer_id` | Bayer ID | Bayer or Flamsteed designation, where there is one |
| `constellation` | Constellation | IAU abbreviation |
| `adopted` | Date of Adoption | `YYYY/MM/DD` |

The page's etymologies, languages, references and images are not extracted.

SHA-256 as fetched and extracted (two fetches ten minutes apart were
byte-identical):

- `modern-iau-star-names.html`:
  `2aa88cb3f0451a59318ba4f1803bbc84e36f8f041b85383bb80a4f1cf264b569`
- `iau_csn.tsv`:
  `56e54d18cef100b16c22c305bf2b2fe571953c1cae27c5c3c598c58eeafad78f`

## How the import reads it

Each name with a HIP number joins the star sky object the star-identity stage
identified by that number (§9.3); no other matching is made. It becomes the
sky object's first name. Where the WGSN spelling has diacritics, its
ASCII-folded form (Mönch → Monch) is also stored, as an ordinary name, so the
keypad's text search finds it. A name with no HIP number, one for a star
PiFinder doesn't hold, and HIP 72105's two names are skipped, and the import
logs how many.
