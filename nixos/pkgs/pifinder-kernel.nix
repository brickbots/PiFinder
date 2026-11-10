{ pkgs, nixos-hardware }:

let
  # The newest Raspberry Pi stable tag. nixos-hardware can be some tags behind.
  # Keep modDirVersion equal to the SUBLEVEL in the tag's Makefile.
  modDirVersion = "6.18.60";
  tag = "stable_20261103";
in
pkgs.callPackage "${nixos-hardware}/raspberry-pi/common/kernel.nix" {
  rpiVersion = 4;
  argsOverride.version = "${modDirVersion}-${tag}";
  argsOverride.modDirVersion = modDirVersion;
  argsOverride.src = pkgs.fetchFromGitHub {
    owner = "raspberrypi";
    repo = "linux";
    inherit tag;
    hash = "sha256-Qx3D2+K7lkH5P1NI4NKqcHXVGoPqAeEiu+bZqBfSdDs=";
  };
  argsOverride.kernelPatches = (with pkgs.kernelPatches; [
    bridge_stp_helper
    request_key_helper
  ]) ++ [
    {
      name = "imx290-optical-black-stream";
      # builtins.path gives the patch its own content-addressed store path.
      # A bare ../patches/… reference resolves inside the flake source tree,
      # making the kernel derivation depend on the whole repo hash — every
      # commit (even Python-only) would rebuild the kernel.
      patch = builtins.path {
        path = ../patches/imx290-optical-black-stream.patch;
        name = "imx290-optical-black-stream.patch";
      };
    }
  ];
}
