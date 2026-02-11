{ pkgs, python ? pkgs.python313 }:
let
  tetra3-src = pkgs.fetchFromGitHub {
    owner = "smroid";
    repo = "cedar-solve";
    rev = "38c3f48f57d1005e9b65cbb26136f9f13ec0a1b0";
    hash = "sha256-63Jc5xuJpAZ2UcdKk19MmwuXpix8EBzNNbJzLbl0VyU=";
  };

  # Hipparcos star catalog for starfield plotting
  hip_main = pkgs.fetchurl {
    url = "https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat";
    sha256 = "1q0n6sa55z92bad8gy6r9axkd802798nxkipjh6iciyn0jqspkjq";
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

    # tetra3/cedar-solve is a git submodule — Nix doesn't include submodule
    # contents, so we fetch it separately and graft it into the source tree.
    rm -rf $out/python/PiFinder/tetra3
    cp -r ${tetra3-src} $out/python/PiFinder/tetra3

    # Hipparcos catalog is gitignored (51MB), fetch and include for starfield plotting
    cp ${hip_main} $out/astro_data/hip_main.dat

    # NixOS: sudo setuid wrapper is at /run/wrappers/bin/sudo, not sw/bin/sudo
    chmod -R u+w $out/python
    substituteInPlace $out/python/PiFinder/sys_utils.py \
      --replace-fail '/run/current-system/sw/bin/sudo' '/run/wrappers/bin/sudo'

    # Pre-compile .pyc bytecode so Python skips compilation at runtime
    python3 -m compileall -q $out/python
  '';
}
