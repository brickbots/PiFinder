{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
    nixos-hardware.url = "github:NixOS/nixos-hardware";
  };

  outputs = { self, nixpkgs, nixos-hardware, ... }: let
    # Shared modules for all PiFinder configurations
    commonModules = [
      nixos-hardware.nixosModules.raspberry-pi-4
      ./nixos/hardware.nix
      ./nixos/networking.nix
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
        boot.initrd.availableKernelModules = lib.mkForce [ "mmc_block" "usbhid" "usb_storage" "vc4" ];
      })
    ];

    mkPifinderSystem = { includeSDImage ? false }: nixpkgs.lib.nixosSystem {
      system = "aarch64-linux";
      modules = commonModules ++ [
        { pifinder.devMode = false; }
        ({ lib, ... }: {
          boot.supportedFilesystems = lib.mkForce [ "vfat" "ext4" ];
        })
      ] ++ nixpkgs.lib.optionals includeSDImage [
        "${nixpkgs}/nixos/modules/installer/sd-card/sd-image-aarch64.nix"
        # Runtime camera selection via /boot/camera.txt
        ({ config, pkgs, lib, ... }:
        let
          # Custom config.txt with camera.txt include
          configTxt = pkgs.writeText "config.txt" ''
            [pi3]
            kernel=u-boot-rpi3.bin

            [pi02]
            kernel=u-boot-rpi3.bin

            [pi4]
            kernel=u-boot-rpi4.bin
            enable_gic=1
            armstub=armstub8-gic.bin

            disable_overscan=1
            arm_boost=1

            [cm4]
            otg_mode=1

            [all]
            arm_64bit=1
            enable_uart=1
            avoid_warnings=1

            # Camera overlay - edit camera.txt and reboot to change camera
            include camera.txt
          '';

          cameraTxt = pkgs.writeText "camera.txt" ''
            # PiFinder Camera Configuration
            # Edit this file and reboot to switch cameras
            # Options: imx296, imx290 (for imx462), imx477
            dtoverlay=imx296
          '';
        in {
          sdImage.populateFirmwareCommands = lib.mkForce ''
            (cd ${pkgs.raspberrypifw}/share/raspberrypi/boot && cp bootcode.bin fixup*.dat start*.elf $NIX_BUILD_TOP/firmware/)

            # Custom config.txt with camera.txt include
            cp ${configTxt} firmware/config.txt
            cp ${cameraTxt} firmware/camera.txt

            # Pi3 files
            cp ${pkgs.ubootRaspberryPi3_64bit}/u-boot.bin firmware/u-boot-rpi3.bin
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2710-rpi-2-b.dtb firmware/
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2710-rpi-3-b.dtb firmware/
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2710-rpi-3-b-plus.dtb firmware/
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2710-rpi-cm3.dtb firmware/
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2710-rpi-zero-2.dtb firmware/
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2710-rpi-zero-2-w.dtb firmware/

            # Pi4 files
            cp ${pkgs.ubootRaspberryPi4_64bit}/u-boot.bin firmware/u-boot-rpi4.bin
            cp ${pkgs.raspberrypi-armstubs}/armstub8-gic.bin firmware/armstub8-gic.bin
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2711-rpi-4-b.dtb firmware/
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2711-rpi-400.dtb firmware/
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2711-rpi-cm4.dtb firmware/
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2711-rpi-cm4s.dtb firmware/
          '';
        })
      ] ++ nixpkgs.lib.optionals (!includeSDImage) [
        # Minimal filesystem stub for closure builds (CI)
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

    # Netboot configuration — NFS root, DHCP network in initrd
    mkPifinderNetboot = nixpkgs.lib.nixosSystem {
      system = "aarch64-linux";
      modules = commonModules ++ [
        { pifinder.devMode = true; }
        { pifinder.cameraType = "imx477"; }  # HQ camera for netboot dev
        ({ lib, pkgs, ... }: {
          # Static passwd/group — NFS can't run activation scripts
          users.mutableUsers = false;
          # DNS for netboot (udhcpc doesn't configure resolvconf properly)
          networking.nameservers = [ "192.168.5.1" "8.8.8.8" ];
          boot.supportedFilesystems = lib.mkForce [ "vfat" "ext4" "nfs" ];
          boot.initrd.supportedFilesystems = [ "nfs" ];
          # Override the minimal module list from commonModules — add network drivers
          # Note: genet (RPi4 ethernet) is built into the kernel, not a module
          boot.initrd.availableKernelModules = lib.mkForce [
            "mmc_block" "usbhid" "usb_storage" "vc4"
          ];
          # Disable predictable interface names so eth0 works
          boot.kernelParams = [ "net.ifnames=0" "biosdevname=0" ];
          boot.initrd.network = {
            enable = true;
          };
          # Manually configure network before NFS mount
          boot.initrd.postDeviceCommands = ''
            # Wait for interface to appear
            for i in $(seq 1 30); do
              if ip link show eth0 >/dev/null 2>&1; then
                break
              fi
              sleep 0.5
            done

            ip link set eth0 up
            udhcpc -i eth0 -t 10 -T 3 -n -q -s /etc/udhcpc.script || true
            ip addr show eth0
          '';
          # NFS root filesystem
          fileSystems."/" = {
            device = "192.168.5.12:/srv/nfs/pifinder";
            fsType = "nfs";
            options = [ "vers=3" "tcp" "nolock" ];
          };
          # Dummy /boot — not used for netboot but NixOS requires it
          fileSystems."/boot" = {
            device = "none";
            fsType = "tmpfs";
            neededForBoot = false;
          };
        })
      ];
    };
    # Custom u-boot with network boot prioritized for netboot
    # Uses direct commands since bootcmd_* env vars may not be defined
    pkgsAarch64 = import nixpkgs { system = "aarch64-linux"; };
    ubootNetboot = pkgsAarch64.ubootRaspberryPi4_64bit.override {
      extraConfig = ''
        CONFIG_BOOTCOMMAND="pci enum; dhcp; pxe get; pxe boot"
      '';
    };
  in {
    nixosConfigurations = {
      # SD card boot — camera selected at runtime via /boot/camera.txt
      pifinder = mkPifinderSystem {};
      # NFS netboot — for development on proxnix
      pifinder-netboot = mkPifinderNetboot;
    };
    images = {
      # SD card image
      pifinder = (mkPifinderSystem { includeSDImage = true; }).config.system.build.sdImage;
    };
    packages.aarch64-linux = {
      uboot-netboot = ubootNetboot;
    };
  };
}
