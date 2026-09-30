{ pkgs, nixos-hardware }:

pkgs.callPackage "${nixos-hardware}/raspberry-pi/common/kernel.nix" {
  rpiVersion = 4;
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
