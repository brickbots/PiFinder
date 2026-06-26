{ pkgs, python ? pkgs.python313 }:
let
  tetra3-src = pkgs.fetchFromGitHub {
    owner = "smroid";
    repo = "cedar-solve";
    rev = "cded265ca1c41e4e526f91e06d3c7ef99bc37288";
    hash = "sha256-eJtBuBmsElEojXLYfYy3gQ/s2+8qjyvOYAqROe4sNO0=";
  };

  # Stable astro data — catalogs, star patterns, ephemeris (~193MB, rarely changes)
  # hip_main.dat is now committed to astro_data/ upstream, so cp -r picks it up.
  astro-data = pkgs.stdenv.mkDerivation {
    pname = "pifinder-astro-data";
    version = "1.0";
    src = ../../astro_data;
    phases = [ "installPhase" ];
    installPhase = ''
      mkdir -p $out
      cp -r $src/* $out/
    '';
  };

  # tetra3/cedar-solve solver — pinned rev, changes only on a submodule bump.
  # Built as its own derivation (examples/tests/docs trimmed, bytecode
  # pre-compiled) and symlinked into pifinder-src, so a routine code change no
  # longer rewrites these ~15MB of stable files. cedar_detect_pb2 ships in the
  # cedar-solve repo, so the symlinked tree is import-complete.
  tetra3 = pkgs.stdenv.mkDerivation {
    pname = "pifinder-tetra3";
    version = "cedar-solve";
    src = tetra3-src;
    nativeBuildInputs = [ python ];
    phases = [ "installPhase" ];
    installPhase = ''
      mkdir -p $out
      cp -r --no-preserve=mode $src/* $out/
      rm -rf $out/examples $out/tests $out/docs
      python3 -m compileall -q $out || true
    '';
  };

  # UI fonts — ~31MB, effectively never change. Own derivation + symlink so they
  # are distributed once and not rewritten on every code change.
  fonts = pkgs.stdenv.mkDerivation {
    pname = "pifinder-fonts";
    version = "1.0";
    src = ../../fonts;
    phases = [ "installPhase" ];
    installPhase = ''
      mkdir -p $out
      cp -r $src/* $out/
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
    rm -rf $out/bin

    # Strip doc photos from images/ but keep welcome.png (used at runtime)
    find $out/images -type f ! -name 'welcome.png' -delete

    # Bulky, stable inputs live in their own derivations and are symlinked in,
    # so a code change rewrites only the (small) code path — not astro-data
    # (~193MB), fonts (~31MB) or tetra3 (~15MB). See ADR 0001.
    rm -rf $out/astro_data
    ln -s ${astro-data} $out/astro_data
    rm -rf $out/fonts
    ln -s ${fonts} $out/fonts

    # tetra3/cedar-solve is a git submodule (empty in the Nix source). Drop the
    # stub before compiling so the dangling python/tetra3 symlink is skipped,
    # then symlink the pre-built solver in afterwards — symlinking before
    # compileall would make it try to write .pyc into the read-only store path.
    rm -rf $out/python/PiFinder/tetra3

    # Pre-compile .pyc bytecode so Python skips compilation at runtime
    chmod -R u+w $out/python
    python3 -m compileall -q $out/python

    ln -s ${tetra3} $out/python/PiFinder/tetra3
  '';
}
