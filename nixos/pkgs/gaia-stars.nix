{ pkgs }:

# Gaia deep-chart star catalog (~454 MB compressed): metadata.json plus
# per-magnitude-band tiles (mag_XX_YY/{index,tiles}.bin), read-only at runtime.
# Fixed-output derivation so an unchanged catalog is never re-downloaded;
# referenced by the system closure (symlinked into PiFinder_data by services.nix)
# so fresh flashes and in-place upgrades both deliver it, like pifinder-src and
# astro_data. A changed catalog is a new store path the device fetches whole —
# Attic's chunk dedup saves server storage on re-upload, not device bandwidth.
pkgs.stdenv.mkDerivation {
  pname = "pifinder-gaia-stars";
  version = "1.0";
  src = pkgs.fetchurl {
    url = "https://files.miker.be/public/pifinder/gaia_stars.tar.zst";
    hash = "sha256-vmsOz7U0X4bnMZrcKjiwIk0YYy/AqRV2+fzaH7qO8wo=";
  };
  nativeBuildInputs = [ pkgs.zstd ];
  unpackPhase = "tar xf $src";
  installPhase = "mv gaia_stars $out";
}
