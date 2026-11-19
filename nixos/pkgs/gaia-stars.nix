{ pkgs }:

# Gaia deep-chart star catalog, catalog_version 3.0 (columnar), 453 MB.
# Format and build: docs/ax/catalog/gaia-star-catalog.md.
#
# Each magnitude band is a shard: a fixed-output derivation that fetches the
# band's tar.zst and unpacks it. Its store path depends only on its name and
# hash, so a nixpkgs update changes no shard, and a band whose files do not
# change keeps its store path. Each shard is below 256 MiB, so the delta
# updater can patch a changed band instead of a full download. `hash` is the
# NAR hash of the unpacked band directory (`nix hash path mag_XX_YY`).
#
# The result is a small directory of links to the shards plus metadata.json.
# services.nix links it into PiFinder_data as gaia_stars. The unpack runs on
# the builder; a device only substitutes the finished paths from the cache.
let
  version = "3.0";
  baseUrl = "https://files.miker.be/public/pifinder/gaia_stars_v3";

  bands = {
    mag_00_06 = "sha256-SC9Xchl4OR2QaRv0lmizYriWVv6HndVdEga8UeSVOKM=";
    mag_06_09 = "sha256-TYV6mR75Fo/03ZEzGhbOW0r9+f6Tk5IWv9V3MSWOr9U=";
    mag_09_12 = "sha256-99E4iSC1zK87fXAgxAln7kBw+L2SQJp+xf4xGn5s+L4=";
    mag_12_14 = "sha256-cHjgD87lULdyAktp6KQwn9ZtkQi9tSYfHxoQA7wo9sw=";
    mag_14_16 = "sha256-OgaOVJ82LLYf40UiFqSwV1F9mRXNC1Id7HKwdfjM7RA=";
    mag_16_17 = "sha256-xJ8FELNBNDOvFlZN1WMLUgI977YbP8QmZba99OkGffw=";
  };

  shard =
    band: hash:
    pkgs.fetchurl {
      name = "pifinder-gaia-${band}-${version}";
      url = "${baseUrl}/${band}.tar.zst";
      inherit hash;
      recursiveHash = true;
      downloadToTemp = true;
      nativeBuildInputs = [ pkgs.zstd ];
      postFetch = ''
        unpackDir="$TMPDIR/unpack"
        mkdir "$unpackDir"
        tar --zstd -xf "$downloadedFile" -C "$unpackDir"
        mv "$unpackDir/${band}" "$out"
      '';
    };

  metadata = pkgs.fetchurl {
    name = "pifinder-gaia-metadata-${version}.json";
    url = "${baseUrl}/metadata.json";
    hash = "sha256-cGF/pKkT0pRuuys58kjtwYjL9Ct84XE51WMgW4oKP4o=";
  };
in
pkgs.linkFarm "pifinder-gaia-stars-${version}" (
  [
    {
      name = "metadata.json";
      path = metadata;
    }
  ]
  ++ pkgs.lib.mapAttrsToList (band: hash: {
    name = band;
    path = shard band hash;
  }) bands
)
