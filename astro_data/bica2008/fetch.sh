#!/bin/sh
# Fetch the Bica et al. (2008) extract from VizieR, as README.md describes:
# every row of the star-cluster, association and emission-nebula tables whose
# Names name an NGC or IC number. VizieR cannot OR two patterns in one query,
# so each table is queried once for NGC and once for IC, and the responses are
# kept verbatim, one after another. A row naming both appears twice.
set -eu
cd "$(dirname "$0")"

curl -sSf -o ReadMe "https://cdsarc.cds.unistra.fr/ftp/J/MNRAS/389/678/ReadMe"

out=bica2008_ngc_ic.tsv
: >"$out"
for table in table3 table4 table5; do
    for prefix in NGC IC; do
        curl -sSf "https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source=J/MNRAS/389/678/${table}&-out=Names,RAJ2000,DEJ2000,Type,amaj,amin,PA,Com&Names=%3D*${prefix}%5B0-9%5D*&-out.max=unlimited" >>"$out"
    done
done
