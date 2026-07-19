{ pkgs, python ? pkgs.python313 }:
let
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
    # Development environments and caches can also live below python/.  In
    # particular, python/.venv is hundreds of MiB and must never become part
    # of the runtime source closure.
    rm -rf $out/python/.venv $out/python/.mypy_cache
    rm -rf $out/python/.pytest_cache $out/python/.ruff_cache
    find $out/python -type d -name __pycache__ -prune -exec rm -rf {} +
    rm -rf $out/case $out/docs $out/gerbers $out/kicad
    rm -rf $out/pi_config_files $out/scripts
    rm -rf $out/bin

    # Strip doc photos from images/ but keep welcome.png (used at runtime)
    find $out/images -type f ! -name 'welcome.png' -delete

    # Bulky, stable inputs live in their own derivations and are symlinked in,
    # so a code change rewrites only the (small) code path — not astro-data
    # (~193MB) or fonts (~31MB). See ADR 0001.
    rm -rf $out/astro_data
    ln -s ${astro-data} $out/astro_data
    rm -rf $out/fonts
    ln -s ${fonts} $out/fonts

    # Pre-compile .pyc bytecode so Python skips compilation at runtime
    chmod -R u+w $out/python
    python3 -m compileall -q $out/python
  '';
}
