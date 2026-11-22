"""
Extract the IAU Catalog of Star Names from the WGSN's page into a TSV.

The IAU Working Group on Star Names publishes its catalog as an HTML table
(modern-iau-star-names.html, fetched verbatim by fetch.sh). The catalog import
reads iau_csn.tsv, which this script writes from that page, so it never parses
HTML. Run it from anywhere, with any Python 3 and no third-party packages:

    python3 extract.py

The TSV keeps the page's rows in the page's order and only the columns that
identify a name's star; the etymologies, references and images stay in the
HTML. Each value is the cell's text with HTML entities decoded and its
surrounding whitespace stripped; a blank cell is an empty field.
"""

import csv
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent
PAGE = HERE / "modern-iau-star-names.html"
TSV = HERE / "iau_csn.tsv"

# The page's columns this keeps, by header, and the TSV's name for each.
COLUMNS = {
    "proper names": "name",
    "NEC+": "wgsn_id",
    "Designation": "designation",
    "HIP": "hip",
    "Bayer ID": "bayer_id",
    "Constellation": "constellation",
    "Date of Adoption": "adopted",
}


class CatalogTable(HTMLParser):
    """The header and body rows of the page's catalog table (id table_1)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.header: List[str] = []
        self.rows: List[List[str]] = []
        self._in_table = False
        self._section: Optional[str] = None
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        if tag == "table" and dict(attrs).get("id") == "table_1":
            self._in_table = True
        elif not self._in_table:
            return
        elif tag in ("thead", "tbody", "tfoot"):
            self._section = tag
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if not self._in_table:
            return
        if tag == "table":
            self._in_table = False
        elif tag in ("td", "th") and self._cell is not None:
            assert self._row is not None
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._section == "thead":
                self.header = self._row
            elif self._section == "tbody":
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def extract(page: Path = PAGE, tsv: Path = TSV) -> int:
    """Write the TSV from the page; return the number of rows."""
    table = CatalogTable()
    table.feed(page.read_text(encoding="utf-8"))
    index = {column: table.header.index(column) for column in COLUMNS}
    with open(tsv, "w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out, delimiter="\t", lineterminator="\n")
        writer.writerow(COLUMNS.values())
        for row in table.rows:
            writer.writerow(row[index[column]] for column in COLUMNS)
    return len(table.rows)


if __name__ == "__main__":
    print(f"{extract()} rows written to {TSV.name}")
