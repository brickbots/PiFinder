{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
    nixos-hardware.url = "github:NixOS/nixos-hardware";
  };

  outputs = { self, nixpkgs, nixos-hardware, ... }: let
    mkPifinderSystem = { includeSDImage ? false, devMode ? false }: nixpkgs.lib.nixosSystem {
      system = "aarch64-linux";
      modules = [
        nixos-hardware.nixosModules.raspberry-pi-4
        ./nixos/hardware.nix
        ./nixos/networking.nix
        { pifinder.devMode = devMode; }
        ./nixos/services.nix
        ./nixos/python-env.nix
        # Headless — strip X11, fonts, docs, desktop bloat
        ({ lib, ... }: {
          services.xserver.enable = false;
          security.polkit.enable = true;
          fonts.fontconfig.enable = false;
          documentation.enable = false;
          documentation.man.enable = false;
          documentation.nixos.enable = false;
          xdg.portal.enable = false;
          services.pipewire.enable = false;
          hardware.pulseaudio.enable = false;
          boot.supportedFilesystems = lib.mkForce ([ "vfat" "ext4" ] ++ lib.optionals devMode [ "nfs" ]);
          boot.initrd.availableKernelModules = lib.mkForce [ "mmc_block" "usbhid" "usb_storage" "vc4" ];
          # NFS netboot support (dev mode only) - NFS and ethernet are built into RPi kernel
          boot.initrd.supportedFilesystems = lib.mkIf devMode [ "nfs" ];
          boot.initrd.network.enable = devMode;
        })
      ] ++ nixpkgs.lib.optionals includeSDImage [
        "${nixpkgs}/nixos/modules/installer/sd-card/sd-image-aarch64.nix"
      ] ++ nixpkgs.lib.optionals (!includeSDImage) [
        # Minimal filesystem stub for closure builds (CI)
        # The SD image module provides real filesystems; this is just for evaluation
        ({ lib, ... }: {
          fileSystems."/" = {
            device = "/dev/disk/by-label/NIXOS_SD";
            fsType = "ext4";
          };
          fileSystems."/boot" = {
            device = "/dev/disk/by-label/FIRMWARE";
            fsType = "vfat";
          };
        })
      ];
    };
  in {
    nixosConfigurations = {
      # Single universal build - camera selected at runtime via /boot/camera.txt
      pifinder = mkPifinderSystem {};
      # Dev config (NFS netboot support)
      pifinder-dev = mkPifinderSystem { devMode = true; };
    };
    images = {
      # Single universal image - camera selected at runtime via /boot/camera.txt
      pifinder = (mkPifinderSystem { includeSDImage = true; }).config.system.build.sdImage;
      # Dev image (NFS netboot support, larger initrd)
      pifinder-dev = (mkPifinderSystem { includeSDImage = true; devMode = true; }).config.system.build.sdImage;
    };
  };
}
