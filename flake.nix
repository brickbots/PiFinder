{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
    nixos-hardware.url = "github:NixOS/nixos-hardware";
  };

  outputs = { self, nixpkgs, nixos-hardware, ... }: let
    mkPifinderSystem = { cameraType, includeSDImage ? false }: nixpkgs.lib.nixosSystem {
      system = "aarch64-linux";
      modules = [
        nixos-hardware.nixosModules.raspberry-pi-4
        ./nixos/hardware.nix
        ./nixos/networking.nix
        ./nixos/services.nix
        ./nixos/python-env.nix
        { pifinder.cameraType = cameraType; }
      ] ++ nixpkgs.lib.optionals includeSDImage [
        "${nixpkgs}/nixos/modules/installer/sd-card/sd-image-aarch64.nix"
      ];
    };
  in {
    nixosConfigurations = {
      pifinder = mkPifinderSystem { cameraType = "imx296"; };
      pifinder-imx296 = mkPifinderSystem { cameraType = "imx296"; };
      pifinder-imx462 = mkPifinderSystem { cameraType = "imx462"; };
      pifinder-imx477 = mkPifinderSystem { cameraType = "imx477"; };
    };
    images = {
      pifinder = (mkPifinderSystem { cameraType = "imx296"; includeSDImage = true; }).config.system.build.sdImage;
      pifinder-imx296 = (mkPifinderSystem { cameraType = "imx296"; includeSDImage = true; }).config.system.build.sdImage;
      pifinder-imx462 = (mkPifinderSystem { cameraType = "imx462"; includeSDImage = true; }).config.system.build.sdImage;
      pifinder-imx477 = (mkPifinderSystem { cameraType = "imx477"; includeSDImage = true; }).config.system.build.sdImage;
    };
  };
}
