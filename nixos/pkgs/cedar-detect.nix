{ pkgs }:
pkgs.stdenv.mkDerivation {
  pname = "cedar-detect-server";
  version = "0.1.0";
  src = ../../bin;
  nativeBuildInputs = [ pkgs.autoPatchelfHook ];
  buildInputs = [ pkgs.stdenv.cc.cc.lib ];
  installPhase = ''
    mkdir -p $out/bin
    cp cedar-detect-server-aarch64 $out/bin/cedar-detect-server
    chmod +x $out/bin/cedar-detect-server
  '';
}
