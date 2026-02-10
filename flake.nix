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
        # Camera specialisations — base is imx462 (default), specialisations for others
        ({ ... }: {
          specialisation = {
            imx296.configuration = { pifinder.cameraType = "imx296"; };
            imx477.configuration = { pifinder.cameraType = "imx477"; };
          };
        })
        ({ lib, ... }: {
          boot.supportedFilesystems = lib.mkForce [ "vfat" "ext4" ];
        })
      ] ++ nixpkgs.lib.optionals includeSDImage [
        "${nixpkgs}/nixos/modules/installer/sd-card/sd-image-aarch64.nix"
        ({ config, pkgs, lib, ... }:
        let
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
          '';
        in {
          sdImage.populateFirmwareCommands = lib.mkForce ''
            (cd ${pkgs.raspberrypifw}/share/raspberrypi/boot && cp bootcode.bin fixup*.dat start*.elf $NIX_BUILD_TOP/firmware/)

            cp ${configTxt} firmware/config.txt

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
        # Camera specialisations for netboot (base is imx477)
        ({ ... }: {
          specialisation = {
            imx296.configuration = { pifinder.cameraType = "imx296"; };
            imx462.configuration = { pifinder.cameraType = "imx462"; };
          };
        })
        ({ lib, pkgs, ... }:
        let
          boot-splash = import ./nixos/pkgs/boot-splash.nix { inherit pkgs; };
        in {
          # Static passwd/group — NFS can't run activation scripts
          users.mutableUsers = false;
          # DNS for netboot (udhcpc doesn't configure resolvconf properly)
          networking.nameservers = [ "192.168.5.1" "8.8.8.8" ];
          boot.supportedFilesystems = lib.mkForce [ "vfat" "ext4" "nfs" ];
          boot.initrd.supportedFilesystems = [ "nfs" ];
          # Add SPI kernel module for early OLED splash
          boot.initrd.kernelModules = [ "spi_bcm2835" ];
          # Override the minimal module list from commonModules — add network drivers
          # Note: genet (RPi4 ethernet) is built into the kernel, not a module
          boot.initrd.availableKernelModules = lib.mkForce [
            "mmc_block" "usbhid" "usb_storage" "vc4"
          ];
          # Add boot-splash to initrd
          boot.initrd.extraUtilsCommands = ''
            copy_bin_and_libs ${boot-splash}/bin/boot-splash
          '';
          # Disable predictable interface names so eth0 works
          boot.kernelParams = [ "net.ifnames=0" "biosdevname=0" ];
          boot.initrd.network = {
            enable = true;
          };
          # Show static splash, then configure network
          boot.initrd.postDeviceCommands = ''
            # Create device nodes for SPI OLED
            mkdir -p /dev
            mknod -m 666 /dev/spidev0.0 c 153 0 2>/dev/null || true
            mknod -m 666 /dev/gpiochip0 c 254 0 2>/dev/null || true

            # Show static splash image (--static flag = display once and exit)
            boot-splash --static || true
            # Wait for interface to appear (up to 30 seconds)
            echo "Waiting for eth0..."
            for i in $(seq 1 60); do
              if ip link show eth0 >/dev/null 2>&1; then
                echo "eth0 found after $i attempts"
                break
              fi
              sleep 0.5
            done

            ip link set eth0 up

            # Wait for link carrier (cable connected)
            echo "Waiting for link carrier..."
            for i in $(seq 1 20); do
              if [ "$(cat /sys/class/net/eth0/carrier 2>/dev/null)" = "1" ]; then
                echo "Link up after $i attempts"
                break
              fi
              sleep 0.5
            done

            # DHCP with retries
            echo "Starting DHCP..."
            for attempt in 1 2 3; do
              if udhcpc -i eth0 -t 5 -T 3 -n -q -s /etc/udhcpc.script; then
                echo "DHCP succeeded on attempt $attempt"
                break
              fi
              echo "DHCP attempt $attempt failed, retrying..."
              sleep 2
            done

            # Verify we got an IP
            if ip addr show eth0 | grep -q "inet "; then
              echo "Network configured:"
              ip addr show eth0
            else
              echo "WARNING: No IP address on eth0!"
              ip addr show eth0
            fi
          '';
          # NFS root filesystem - NFSv4 with disabled caching for Nix compatibility
          fileSystems."/" = {
            device = "192.168.5.12:/srv/nfs/pifinder";
            fsType = "nfs";
            options = [ "vers=4" "noac" "actimeo=0" ];
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

    # Bootstrap system for migration from RPi OS
    # Minimal NixOS that boots, connects to network, and runs nixos-rebuild switch
    # NOTE: Does NOT use nixos-hardware module to avoid pulling in linux-firmware (659MB)
    mkBootstrapSystem = { includeSDImage ? false }: nixpkgs.lib.nixosSystem {
      system = "aarch64-linux";
      modules = [
        # Inline minimal Pi4 hardware config instead of nixos-hardware module
        ({ lib, ... }: {
          # Basic Pi 4 kernel - no extra firmware needed for bootstrap
          boot.kernelPackages = lib.mkDefault (import nixpkgs { system = "aarch64-linux"; }).linuxPackages_rpi4;
          hardware.enableRedistributableFirmware = lib.mkForce false;
          hardware.firmware = lib.mkForce [];
        })
        ./nixos/bootstrap.nix
      ] ++ nixpkgs.lib.optionals includeSDImage [
        "${nixpkgs}/nixos/modules/installer/sd-card/sd-image-aarch64.nix"
        ({ pkgs, lib, ... }: {
          # Simplified firmware population for bootstrap
          sdImage.populateFirmwareCommands = lib.mkForce ''
            (cd ${pkgs.raspberrypifw}/share/raspberrypi/boot && cp bootcode.bin fixup*.dat start*.elf $NIX_BUILD_TOP/firmware/)

            # Minimal config.txt for Pi 4
            cat > firmware/config.txt <<EOF
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
            EOF

            # Pi4 files only (bootstrap is Pi 4 only for now)
            cp ${pkgs.ubootRaspberryPi4_64bit}/u-boot.bin firmware/u-boot-rpi4.bin
            cp ${pkgs.raspberrypi-armstubs}/armstub8-gic.bin firmware/armstub8-gic.bin
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2711-rpi-4-b.dtb firmware/
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2711-rpi-400.dtb firmware/
            cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2711-rpi-cm4.dtb firmware/
          '';
        })
      ];
    };
  in {
    nixosConfigurations = {
      # SD card boot — camera baked into DT, switched via specialisations
      pifinder = mkPifinderSystem {};
      # NFS netboot — for development on proxnix
      pifinder-netboot = mkPifinderNetboot;
      # Bootstrap for migration from RPi OS
      pifinder-bootstrap = mkBootstrapSystem {};
    };
    images = {
      # SD card image
      pifinder = (mkPifinderSystem { includeSDImage = true; }).config.system.build.sdImage;
      # Bootstrap image for migration
      bootstrap = (mkBootstrapSystem { includeSDImage = true; }).config.system.build.sdImage;
    };
    packages.aarch64-linux = {
      uboot-netboot = ubootNetboot;
    };
  };
}
