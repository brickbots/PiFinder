#!/bin/sh
# Fetch the RC3 extract from VizieR, as README.md describes: every row whose
# BT is coded "V" (a V-band magnitude). "==V" is VizieR's strict equality; a
# plain "V" is caseless and would add the twelve rows coded "v" (a variable
# nucleus).
set -eu
cd "$(dirname "$0")"

curl -sSf -o ReadMe "https://cdsarc.cds.unistra.fr/ftp/VII/155/ReadMe"
curl -sSf -o rc3_bt_code_v.tsv "https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source=VII/155/rc3&-out=name,altname,PGC,RA2000,DE2000,BT,BT_code,e_BT&BT_code=%3D%3DV&-out.max=unlimited"
