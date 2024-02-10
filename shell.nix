{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  packages = with pkgs; [
    (python39.withPackages (ps: [ ps.pip ]))
  ];
}
