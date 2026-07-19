{ pkgs, nixos-hardware }:

pkgs.callPackage "${nixos-hardware}/raspberry-pi/common/kernel.nix" {
  rpiVersion = 4;
  argsOverride.kernelPatches = (with pkgs.kernelPatches; [
    bridge_stp_helper
    request_key_helper
  ]) ++ [
    {
      name = "imx290-optical-black-stream";
      patch = ../patches/imx290-optical-black-stream.patch;
    }
  ];
}
