#!/bin/sh
# Fetch the IAU Catalog of Star Names from the WGSN's page, as README.md
# describes, and extract the TSV the catalog import reads. The page is kept
# verbatim; extract.py writes iau_csn.tsv from it.
set -eu
cd "$(dirname "$0")"

curl -sSfL -o modern-iau-star-names.html "https://exopla.net/star-names/modern-iau-star-names/"
python3 extract.py
