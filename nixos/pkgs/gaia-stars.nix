{ pkgs }:

# Gaia deep-chart star catalog (~454 MB compressed, 604 MB unpacked):
# metadata.json plus per-magnitude-band tiles (mag_XX_YY/{index,tiles}.bin),
# read-only at runtime. Referenced by the system closure (symlinked into
# PiFinder_data by services.nix), so fresh flashes and in-place upgrades both
# deliver it, like pifinder-src and astro_data.
#
# This is a fixed-output derivation. The unpack runs inside the fetch, and
# `hash` is the NAR hash of the unpacked tree. The store path therefore depends
# only on the name and this hash. A nixpkgs update does not change it, so a
# device does not download the catalog again. A changed catalog needs a new
# hash and is a new store path that each device downloads in full.
#
# The unpack runs on the builder. A device only substitutes the finished path
# from the cache.
pkgs.fetchurl {
  name = "pifinder-gaia-stars-1.0";
  url = "https://files.miker.be/public/pifinder/gaia_stars.tar.zst";
  hash = "sha256-yD6zITKN6PANJkAdofkycQUi8eltvpbMqOdyAChKtSE=";
  recursiveHash = true;
  downloadToTemp = true;
  nativeBuildInputs = [ pkgs.zstd ];
  postFetch = ''
    unpackDir="$TMPDIR/unpack"
    mkdir "$unpackDir"
    tar --zstd -xf "$downloadedFile" -C "$unpackDir"
    mv "$unpackDir/gaia_stars" "$out"
  '';
}
