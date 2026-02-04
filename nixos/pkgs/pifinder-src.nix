{ pkgs }:
pkgs.stdenv.mkDerivation {
  pname = "pifinder-src";
  version = "0.0.1";
  src = ../..;

  phases = [ "installPhase" ];

  installPhase = ''
    mkdir -p $out

    # Python source (the application)
    cp -r $src/python $out/python

    # Astronomical data (catalogs, star patterns, etc.)
    cp -r $src/astro_data $out/astro_data

    # Default config at repo root level
    cp $src/default_config.json $out/default_config.json

    # Version info
    cp $src/versions.json $out/versions.json
  '';
}
