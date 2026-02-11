{ pkgs }:
pkgs.rustPlatform.buildRustPackage rec {
  pname = "cedar-detect-server";
  version = "0.5.0-unstable-2026-02-11";

  src = pkgs.fetchFromGitHub {
    owner = "smroid";
    repo = "cedar-detect";
    rev = "da6be9d318976a1a0853ecdf6dd6cefe41615352";
    hash = "sha256-SqWJ35cBOSCu8w5nK2lcdlMWK/bHINatzjr/p+MH3/o=";
  };

  cargoLock.lockFile = ./cedar-detect-Cargo.lock;

  postPatch = ''
    ln -s ${./cedar-detect-Cargo.lock} Cargo.lock
  '';

  nativeBuildInputs = [ pkgs.protobuf ];

  cargoBuildFlags = [ "--bin" "cedar-detect-server" ];

  meta = {
    description = "Cedar Detect star detection gRPC server";
    homepage = "https://github.com/smroid/cedar-detect";
  };
}
