{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    nixos-hardware.url = "github:NixOS/nixos-hardware";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, nixos-hardware, pyproject-nix, uv2nix, pyproject-build-systems, ... }: let
    # Flake inputs the python-env module needs, passed via specialArgs.
    pythonInputs = { inherit nixos-hardware pyproject-nix uv2nix pyproject-build-systems; };
    crossPkgsAarch64 = import nixpkgs {
      localSystem = "x86_64-linux";
      crossSystem = "aarch64-linux";
    };
    pifinderCrossKernel = import ./nixos/pkgs/pifinder-kernel.nix {
      pkgs = crossPkgsAarch64;
      inherit nixos-hardware;
    };
    # Headless config shared by all profiles
    headlessModule = { lib, ... }: {
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
    };

    # Shared modules for all PiFinder configurations
    commonModules = [
      nixos-hardware.nixosModules.raspberry-pi-4
      ./nixos/hardware.nix
      ./nixos/networking.nix
      ./nixos/services.nix
      ./nixos/python-env.nix
      headlessModule
    ];

    # Migration profile — minimal bootable system, full config fetched on first boot
    migrationModules = [
      nixos-hardware.nixosModules.raspberry-pi-4
      ./nixos/hardware.nix
      ./nixos/networking.nix
      ./nixos/wifi-fallback-minimal.nix
      ./nixos/device.nix
      headlessModule
    ];

    mkPifinderSystem = { includeSDImage ? false, kernel ? null }:
    nixpkgs.lib.nixosSystem {
      system = "aarch64-linux";
      # pifinderKernel must always be present in specialArgs: a NixOS module's
      # `arg ? default` formal is not honoured by the module system, so an
      # absent arg fails evaluation. null selects the natively-built patched
      # kernel; a non-null value injects a prebuilt (e.g. cross-built) one.
      specialArgs = pythonInputs // { pifinderKernel = kernel; };
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
        ({ config, pkgs, lib, ... }: {
          # Catalog images (~5GB compressed) are not baked into the SD image: the
          # app fetches per-object images on demand from the CDN (get_images.py)
          # and renders a placeholder when one is absent. Shipping only the empty
          # data dir keeps the image slim and the build fast.
          #
          # current-build.json seeds the device's identity with its own store
          # path; human version labels come from the update manifest (which maps
          # store paths to versions), and every upgrade rewrites this file.
          sdImage.populateRootCommands = ''
            mkdir -p ./files/home/pifinder/PiFinder_data
            mkdir -p ./files/var/lib/pifinder
            printf '{"store_path": "%s"}\n' "${config.system.build.toplevel}" \
              > ./files/var/lib/pifinder/current-build.json
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

    mkPifinderMigration = { includeSDImage ? false }: nixpkgs.lib.nixosSystem {
      system = "aarch64-linux";
      specialArgs = pythonInputs // { pifinderKernel = null; };
      modules = migrationModules ++ [
        { pifinder.devMode = false; }
        ({ lib, ... }: {
          boot.supportedFilesystems = lib.mkForce [ "vfat" "ext4" ];
          boot.loader.timeout = 0;
        })
      ] ++ nixpkgs.lib.optionals includeSDImage [
        "${nixpkgs}/nixos/modules/installer/sd-card/sd-image-aarch64.nix"
        ({ config, pkgs, lib, ... }: {
          sdImage.populateRootCommands = ''
            mkdir -p ./files/home/pifinder/PiFinder_data
            mkdir -p ./files/var/lib/pifinder
            # ADR 0003: last-ditch fallback for first-boot resolution when the
            # update manifest is unreachable. The manifest is the primary
            # source; this file is otherwise ignored and removed on success.
            # (The old closure-based tarball builder used to write it; the
            # image-based pipeline must bake it.)
            echo "${(mkPifinderSystem {}).config.system.build.toplevel}" \
              > ./files/var/lib/pifinder/first-boot-target
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
      specialArgs = pythonInputs // { pifinderKernel = null; };
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

    configTxt = pkgsAarch64.writeText "config.txt" ''
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

    # Reproducible development environment for both desktop Linux and the
    # aarch64 PiFinder itself. Runtime-native bindings come from Nix, just as
    # they do in the systemd service; uv supplies the locked Python workspace.
    mkDevShell = system: let
      pkgs = import nixpkgs {
        inherit system;
        overlays = [(final: prev: {
          libcamera = prev.libcamera.overrideAttrs (old: {
            mesonFlags = (old.mesonFlags or []) ++ [ "-Dpycamera=enabled" ];
            buildInputs = (old.buildInputs or []) ++ [
              final.python313
              final.python313.pkgs.pybind11
            ];
          });
        })];
      };
      pyPkgs = import ./nixos/pkgs/uv-python.nix {
        inherit pkgs pyproject-nix uv2nix pyproject-build-systems;
      };
      cedar-detect = import ./nixos/pkgs/cedar-detect.nix { inherit pkgs; };
    in pkgs.mkShell {
      packages = [
        pyPkgs.devEnv
        pkgs.bashInteractive
        pkgs.ruff
        pkgs.uv
        pkgs.git
        pkgs.rsync
        pkgs.gobject-introspection
        pkgs.networkmanager
        pkgs.libcamera
        pkgs.gpsd
        cedar-detect
      ];
      shellHook = ''
        export PYTHONPATH="${pkgs.libcamera}/lib/python3.13/site-packages:$PYTHONPATH"
        export GI_TYPELIB_PATH="${pkgs.lib.makeSearchPath "lib/girepository-1.0" [
          pkgs.networkmanager
          pkgs.glib.out
          pkgs.gobject-introspection
        ]}:$GI_TYPELIB_PATH"
        export LIBCAMERA_IPA_MODULE_PATH="${pkgs.libcamera}/lib/libcamera"
      '';
    };

  in {
    nixosConfigurations = {
      # SD card boot — camera baked into DT, switched via specialisations
      pifinder = mkPifinderSystem {};
      # Cache-compatible aarch64 userspace with a kernel cross-built on x86_64.
      pifinder-fast = mkPifinderSystem { kernel = pifinderCrossKernel; };
      # Migration — minimal bootable system, defers full system to first boot
      pifinder-migration = mkPifinderMigration {};
      # NFS netboot — for development on proxnix
      pifinder-netboot = mkPifinderNetboot;
    };
    images = {
      pifinder = (mkPifinderSystem { includeSDImage = true; }).config.system.build.sdImage;
      pifinder-migration = (mkPifinderMigration { includeSDImage = true; }).config.system.build.sdImage;
    };
    packages.aarch64-linux = {
      uboot-sd = ubootSD;
      uboot-netboot = ubootNetboot;
      migration-boot-firmware = pkgsAarch64.runCommand "migration-boot-firmware" {} ''
        mkdir -p $out
        FW=${pkgsAarch64.raspberrypifw}/share/raspberrypi/boot

        # RPi firmware
        cp $FW/bootcode.bin $FW/fixup*.dat $FW/start*.elf $out/

        # Pi3 DTBs
        cp $FW/bcm2710-rpi-2-b.dtb $FW/bcm2710-rpi-3-b.dtb $FW/bcm2710-rpi-3-b-plus.dtb $out/
        cp $FW/bcm2710-rpi-cm3.dtb $FW/bcm2710-rpi-zero-2.dtb $FW/bcm2710-rpi-zero-2-w.dtb $out/

        # Pi4 DTBs
        cp $FW/bcm2711-rpi-4-b.dtb $FW/bcm2711-rpi-400.dtb $FW/bcm2711-rpi-cm4.dtb $FW/bcm2711-rpi-cm4s.dtb $out/

        # config.txt
        cp ${configTxt} $out/config.txt

        # u-boot binaries
        cp ${pkgsAarch64.ubootRaspberryPi3_64bit}/u-boot.bin $out/u-boot-rpi3.bin
        cp ${ubootSD}/u-boot.bin $out/u-boot-rpi4.bin

        # armstub
        cp ${pkgsAarch64.raspberrypi-armstubs}/armstub8-gic.bin $out/armstub8-gic.bin
      '';
    };

    packages.x86_64-linux.pifinder-kernel-cross = pifinderCrossKernel;

    devShells = {
      x86_64-linux.default = mkDevShell "x86_64-linux";
      aarch64-linux.default = mkDevShell "aarch64-linux";
    };

    devShells.aarch64-darwin.default = let
      pkgs = import nixpkgs { system = "aarch64-darwin"; };
      pyPkgs = import ./nixos/pkgs/uv-python-darwin.nix {
        inherit pkgs pyproject-nix uv2nix pyproject-build-systems;
      };
      cedar-detect = import ./nixos/pkgs/cedar-detect.nix { inherit pkgs; };
    in pkgs.mkShell {
      packages = [ pyPkgs.devEnv pkgs.ruff pkgs.uv cedar-detect ];
    };
  };
}
