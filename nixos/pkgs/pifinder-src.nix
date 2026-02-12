{ pkgs, python ? pkgs.python313 }:
let
  tetra3-src = pkgs.fetchFromGitHub {
    owner = "smroid";
    repo = "cedar-solve";
    rev = "cded265ca1c41e4e526f91e06d3c7ef99bc37288";
    hash = "sha256-eJtBuBmsElEojXLYfYy3gQ/s2+8qjyvOYAqROe4sNO0=";
  };

  # Hipparcos star catalog for starfield plotting
  hip_main = pkgs.fetchurl {
    url = "https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat";
    sha256 = "1q0n6sa55z92bad8gy6r9axkd802798nxkipjh6iciyn0jqspkjq";
  };

  # Stable astro data — catalogs, star patterns, ephemeris (~193MB, rarely changes)
  astro-data = pkgs.stdenv.mkDerivation {
    pname = "pifinder-astro-data";
    version = "1.0";
    src = ../../astro_data;
    phases = [ "installPhase" ];
    installPhase = ''
      mkdir -p $out
      cp -r $src/* $out/
      cp ${hip_main} $out/hip_main.dat
    '';
  };

in
pkgs.stdenv.mkDerivation {
  pname = "pifinder-src";
  version = "0.0.1";
  src = ../..;

  nativeBuildInputs = [ python ];
  phases = [ "installPhase" ];

  installPhase = ''
    mkdir -p $out

    # Copy everything except build artifacts and non-runtime directories
    cp -r --no-preserve=mode $src/* $out/ || true

    # Remove directories not needed at runtime
    rm -rf $out/.git $out/.github $out/nixos $out/result* $out/.venv
    rm -rf $out/case $out/docs $out/gerbers $out/kicad
    rm -rf $out/migration_source $out/pi_config_files $out/scripts
    rm -rf $out/bin $out/images

    # Replace astro_data with symlink to stable derivation
    rm -rf $out/astro_data
    ln -s ${astro-data} $out/astro_data

    # tetra3/cedar-solve is a git submodule — Nix doesn't include submodule
    # contents, so we fetch it separately and graft it into the source tree.
    rm -rf $out/python/PiFinder/tetra3
    cp -r ${tetra3-src} $out/python/PiFinder/tetra3

    # Pre-compile .pyc bytecode so Python skips compilation at runtime
    chmod -R u+w $out/python
    python3 -m compileall -q $out/python
  '';
}
