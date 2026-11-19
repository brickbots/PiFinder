#!/usr/bin/env bash
#
# Regenerate the vendored Perek-Kohoutek source snapshot.
#
# Run from this directory. Files are committed to the repo, so run this only
# when you want to refresh the snapshot; the catalog build reads the files,
# never the network.
#
# See PROVENANCE.md for what each file contains and which epoch it uses.

set -euo pipefail

cd "$(dirname "$0")"

CDS="https://cdsarc.cds.unistra.fr/ftp"
SIMBAD="https://simbad.cds.unistra.fr/simbad/sim-tap/sync"

# CDS throttles rapid consecutive requests and answers with an empty body,
# so pause between downloads.
fetch() {
    local url="$1" out="$2"
    echo "fetching ${url}"
    curl -sS -f -o "${out}" "${url}"
    sleep 2
}

fetch "${CDS}/IV/24/ReadMe" ReadMe_IV24
fetch "${CDS}/V/84/ReadMe" ReadMe_V84

for spec in "IV/24/table2:table2.dat" "IV/24/table4:table4.dat" \
            "V/84/main:main.dat" "V/84/diam:diam.dat"; do
    src="${spec%%:*}"
    out="${spec##*:}"
    fetch "${CDS}/${src}.dat.gz" "${out}.gz"
    gunzip -f "${out}.gz"
done

# Every SIMBAD object carrying a PK identifier, with its ICRS position.
echo "fetching SIMBAD PK positions"
curl -sS -f -X POST "${SIMBAD}" \
    --data-urlencode "REQUEST=doQuery" \
    --data-urlencode "LANG=ADQL" \
    --data-urlencode "FORMAT=tsv" \
    --data-urlencode "MAXREC=200000" \
    --data-urlencode "QUERY=SELECT i.id, b.main_id, b.ra, b.dec, b.otype \
        FROM ident i JOIN basic b ON i.oidref = b.oid \
        WHERE i.id LIKE 'PK %'" \
    -o simbad_pk.tsv
sleep 2

# Cross-identifications for those same objects, restricted to the designation
# families PiFinder has a catalog for.
echo "fetching SIMBAD PK cross-identifications"
curl -sS -f -X POST "${SIMBAD}" \
    --data-urlencode "REQUEST=doQuery" \
    --data-urlencode "LANG=ADQL" \
    --data-urlencode "FORMAT=tsv" \
    --data-urlencode "MAXREC=200000" \
    --data-urlencode "QUERY=SELECT i1.id AS pk_id, i2.id AS alias \
        FROM ident i1 JOIN ident i2 ON i1.oidref = i2.oidref \
        WHERE i1.id LIKE 'PK %' \
          AND (i2.id LIKE 'NGC %' OR i2.id LIKE 'IC %' OR i2.id LIKE 'M %' \
               OR i2.id LIKE 'PN A66%' OR i2.id LIKE 'SH 2-%')" \
    -o simbad_pk_aliases.tsv

echo "done"
wc -l ./*.dat ./*.tsv
