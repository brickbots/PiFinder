{ pkgs }:

pkgs.stdenv.mkDerivation {
  pname = "boot-splash";
  version = "0.1.0";

  src = ./.;

  buildInputs = [ pkgs.linuxHeaders ];

  buildPhase = ''
    $CC -O2 -Wall -o boot-splash boot-splash.c
  '';

  installPhase = ''
    mkdir -p $out/bin
    cp boot-splash $out/bin/
  '';

  meta = {
    description = "Early boot splash for PiFinder OLED display";
    platforms = [ "aarch64-linux" ];
  };
}
