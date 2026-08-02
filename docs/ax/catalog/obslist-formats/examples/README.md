# CSV import examples

Sample CSV observing lists exercising every path of the lenient CSV reader
(`read_csv` in `python/PiFinder/obslist_formats.py`). Drop one into the
`obslists/` folder of the PiFinder's shared data and load it, or read it directly
with `obslist_formats.read_file(path)`.

| File | Exercises | What to expect |
|---|---|---|
| `01_decimal_degrees.csv` | lowercase `name,ra,dec,mag`, decimal degrees, non-catalog labels | three OBS coordinate targets |
| `02_ra_hours.csv` | `RA_h` hours hint + catalog names | RA scaled ×15; `M 3` / `M 13` auto-match |
| `03_sexagesimal.csv` | `13h 43m 26s` / `+28° 14' 09"` + `Type` | NGC objects auto-match |
| `04_colon.csv` | `HH:MM:SS` / `±DD:MM:SS`, no magnitude | NGC objects auto-match |
| `05_aliases_whitespace.csv` | aliased headers (`RA_deg`, `DEC`, `VMag`, `Obj_Type`) and padded values | whitespace stripped, fields mapped |
| `06_matching.csv` | auto-match vs no-match vs opt-out | `M 13` matches; `mystery blob` and `_M 13` stay coordinate targets |
| `07_bad_headers.csv` | every header unrecognized | empty name, coordinates fall back to `0.0` |
| `08_partial_bad_header.csv` | one column misnamed (`Declination`) | that column is dropped — dec becomes `0.0` |
| `09_mixed_forms.csv` | decimal, colon and sexagesimal rows in one file | each row parses on its own form |

Matching is spacing- and case-insensitive (via `ui_utils.normalize`): `M 3`,
`M3` and `NGC 224` all resolve. To keep your own coordinates for a name the
catalog would match, give it a non-designation label such as `_M 3`.
