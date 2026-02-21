{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
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
      # Pass git revision to pifinder-src for build identity
      ({ ... }: {
        _module.args.pifinderGitRev = self.shortRev or self.dirtyShortRev or "unknown";
      })
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
        services.pulseaudio.enable = false;
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
          boot.loader.timeout = 0;
        })
      ] ++ nixpkgs.lib.optionals includeSDImage [
        "${nixpkgs}/nixos/modules/installer/sd-card/sd-image-aarch64.nix"
        ({ config, pkgs, lib, ... }:
        let
          ubootSD = pkgs.ubootRaspberryPi4_64bit.override {
            extraConfig = ''
              CONFIG_CMD_PXE=y
              CONFIG_CMD_SYSBOOT=y
              CONFIG_BOOTDELAY=0
              CONFIG_PREBOOT=""
              CONFIG_BOOTCOMMAND="sysboot mmc 0:2 any 0x02400000 /boot/extlinux/extlinux.conf"
              CONFIG_PCI=n
              CONFIG_USB=n
              CONFIG_CMD_USB=n
              CONFIG_CMD_PCI=n
              CONFIG_USB_KEYBOARD=n
              CONFIG_BCMGENET=n
            '';
          };
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
          catalog-images = pkgs.stdenv.mkDerivation {
            pname = "pifinder-catalog-images";
            version = "1.0";
            src = pkgs.fetchurl {
              url = "https://files.miker.be/public/pifinder/catalog_images.tar.zst";
              hash = "sha256-20YOmO2qy2W27nIFV4Aqibu0MLip4gymHrfe411+VNg=";
            };
            nativeBuildInputs = [ pkgs.zstd ];
            unpackPhase = "tar xf $src";
            installPhase = "mv catalog_images $out";
          };
          gaia-stars = pkgs.stdenv.mkDerivation {
            pname = "pifinder-gaia-stars";
            version = "1.0";
            src = pkgs.fetchurl {
              url = "https://files.miker.be/public/pifinder/gaia_stars.tar.zst";
              hash = "sha256-vmsOz7U0X4bnMZrcKjiwIk0YYy/AqRV2+fzaH7qO8wo=";
            };
            nativeBuildInputs = [ pkgs.zstd ];
            unpackPhase = "tar xf $src";
            installPhase = "mv gaia_stars $out";
          };
        in {
          sdImage.populateRootCommands = ''
            mkdir -p ./files/home/pifinder/PiFinder_data
            cp -r ${catalog-images} ./files/home/pifinder/PiFinder_data/catalog_images
            chmod -R u+w ./files/home/pifinder/PiFinder_data/catalog_images
            cp -r ${gaia-stars} ./files/home/pifinder/PiFinder_data/gaia_stars
            chmod -R u+w ./files/home/pifinder/PiFinder_data/gaia_stars
          '';
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
            cp ${ubootSD}/u-boot.bin firmware/u-boot-rpi4.bin
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
          fileSystems."/boot/firmware" = {
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
        { pifinder.cameraType = nixpkgs.lib.mkDefault "imx477"; }  # HQ camera for netboot dev
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
    # Custom u-boot variants
    pkgsAarch64 = import nixpkgs { system = "aarch64-linux"; };
    # SD boot: skip PCI/USB/net probe, go straight to mmc extlinux
    ubootSD = pkgsAarch64.ubootRaspberryPi4_64bit.override {
      extraConfig = ''
        CONFIG_CMD_PXE=y
        CONFIG_CMD_SYSBOOT=y
        CONFIG_BOOTDELAY=0
        CONFIG_PREBOOT=""
        CONFIG_BOOTCOMMAND="sysboot mmc 0:2 any 0x02400000 /boot/extlinux/extlinux.conf"
        CONFIG_PCI=n
        CONFIG_USB=n
        CONFIG_CMD_USB=n
        CONFIG_CMD_PCI=n
        CONFIG_USB_KEYBOARD=n
        CONFIG_BCMGENET=n
      '';
    };
    # Netboot: PCI + DHCP + PXE
    ubootNetboot = pkgsAarch64.ubootRaspberryPi4_64bit.override {
      extraConfig = ''
        CONFIG_BOOTCOMMAND="pci enum; dhcp; pxe get; pxe boot"
      '';
    };

  in {
    nixosConfigurations = {
      # SD card boot — camera baked into DT, switched via specialisations
      pifinder = mkPifinderSystem {};
      # NFS netboot — for development on proxnix
      pifinder-netboot = mkPifinderNetboot;
    };
    images = {
      # SD card image
      pifinder = (mkPifinderSystem { includeSDImage = true; }).config.system.build.sdImage;
      # Migration bootstrap tarball
      bootstrap = let
        system = mkPifinderSystem {};
        toplevel = system.config.system.build.toplevel;
        pkgs = import nixpkgs { system = "aarch64-linux"; };
        closure = pkgs.closureInfo { rootPaths = [ toplevel ]; };
        kernelParams = builtins.concatStringsSep " " system.config.boot.kernelParams;
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
        fw = "${pkgs.raspberrypifw}/share/raspberrypi/boot";
      in pkgs.stdenv.mkDerivation {
        name = "pifinder-bootstrap-tarball";
        __structuredAttrs = true;
        unsafeDiscardReferences.out = true;
        nativeBuildInputs = [ pkgs.zstd ];
        buildCommand = ''
          root=$(mktemp -d)

          # Copy store closure into isolated root (avoids sandbox nix symlink)
          mkdir -p "$root/nix/store"
          while IFS= read -r path; do
            cp -a "$path" "$root$path"
          done < ${closure}/store-paths

          # Nix DB registration for nix-store --load-db
          cp ${closure}/registration "$root/nix-path-registration"

          # System profile symlink
          mkdir -p "$root/nix/var/nix/profiles"
          ln -s ${toplevel} "$root/nix/var/nix/profiles/system"

          # Boot firmware (migration init moves these to FAT32 partition)
          mkdir -p "$root/boot"
          cp ${fw}/bootcode.bin "$root/boot/"
          cp ${fw}/fixup4.dat "$root/boot/"
          cp ${fw}/start4.elf "$root/boot/"
          cp ${pkgs.raspberrypi-armstubs}/armstub8-gic.bin "$root/boot/"
          cp ${ubootSD}/u-boot.bin "$root/boot/u-boot-rpi4.bin"
          cp ${pkgs.ubootRaspberryPi3_64bit}/u-boot.bin "$root/boot/u-boot-rpi3.bin"
          cp ${configTxt} "$root/boot/config.txt"

          # Device trees
          cp ${fw}/bcm2711-rpi-4-b.dtb "$root/boot/"
          cp ${fw}/bcm2711-rpi-400.dtb "$root/boot/"
          cp ${fw}/bcm2711-rpi-cm4.dtb "$root/boot/"
          cp ${fw}/bcm2710-rpi-3-b.dtb "$root/boot/"
          cp ${fw}/bcm2710-rpi-3-b-plus.dtb "$root/boot/"
          cp ${fw}/bcm2710-rpi-zero-2.dtb "$root/boot/"
          cp ${fw}/bcm2710-rpi-zero-2-w.dtb "$root/boot/"

          # Bootloader config
          mkdir -p "$root/boot/extlinux"
          cat > "$root/boot/extlinux/extlinux.conf" <<EXTLINUX
          DEFAULT nixos
          LABEL nixos
            LINUX ${toplevel}/kernel
            INITRD ${toplevel}/initrd
            APPEND init=${toplevel}/init ${kernelParams}
          EXTLINUX

          # Create tarball
          mkdir -p $out/tarball $out/nix-support
          (cd "$root" && tar --sort=name --mtime='@1' --owner=0 --group=0 --numeric-owner -c * \
            | zstd -T0 -8 > $out/tarball/pifinder-bootstrap.tar.zst)
          echo "file system-tarball $out/tarball/pifinder-bootstrap.tar.zst" > $out/nix-support/hydra-build-products
        '';
      };
    };
    packages.aarch64-linux = {
      uboot-sd = ubootSD;
      uboot-netboot = ubootNetboot;
    };

    devShells.x86_64-linux.default = let
      pkgs = import nixpkgs { system = "x86_64-linux"; };
      pyPkgs = import ./nixos/pkgs/python-packages.nix { inherit pkgs; };
      cedar-detect = import ./nixos/pkgs/cedar-detect.nix { inherit pkgs; };
    in pkgs.mkShell {
      packages = [ pyPkgs.devEnv pkgs.ruff cedar-detect ];
    };
  };
}
