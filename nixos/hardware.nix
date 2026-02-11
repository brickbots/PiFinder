{ config, lib, pkgs, ... }:
let
  cfg = config.pifinder;

  # Camera driver name mapping
  cameraDriver = {
    imx296 = "imx296";
    imx462 = "imx290";  # imx462 uses imx290 driver
    imx477 = "imx477";
  }.${cfg.cameraType};

  # Compile DTS text to DTBO
  compileOverlay = name: dtsText: pkgs.deviceTree.compileDTS {
    name = "${name}-dtbo";
    dtsFile = pkgs.writeText "${name}.dts" dtsText;
  };

  # SPI0 — no nixos-hardware option, use custom overlay
  spi0Dtbo = compileOverlay "spi0" ''
    /dts-v1/;
    /plugin/;
    / { compatible = "brcm,bcm2711"; };
    &spi0 { status = "okay"; };
  '';

  # UART3 for GPS on /dev/ttyAMA1
  uart3Dtbo = compileOverlay "uart3" ''
    /dts-v1/;
    /plugin/;
    / { compatible = "brcm,bcm2711"; };
    &uart3 { status = "okay"; };
  '';

  # I2C1 (ARM bus) — nixos-hardware overlay is bypassed by our mkForce DTB package
  i2c1Dtbo = compileOverlay "i2c1" ''
    /dts-v1/;
    /plugin/;
    / { compatible = "brcm,bcm2711"; };
    &i2c1 {
      status = "okay";
      clock-frequency = <${toString cfg.i2cFrequency}>;
    };
  '';

  # PWM on GPIO 13 (PWM channel 1) for keypad backlight
  # GPIO 13 = PWM0_1 when ALT0 (function 4)
  pwmDtbo = compileOverlay "pwm" ''
    /dts-v1/;
    /plugin/;
    / { compatible = "brcm,bcm2711"; };
    &gpio {
      pwm_pin13: pwm_pin13 {
        brcm,pins = <13>;
        brcm,function = <4>;  /* ALT0 = PWM0_1 */
      };
    };
    &pwm {
      status = "okay";
      pinctrl-names = "default";
      pinctrl-0 = <&pwm_pin13>;
    };
  '';

  # Camera overlay from kernel's DTB overlays directory
  cameraDtbo = "${config.boot.kernelPackages.kernel}/dtbs/overlays/${cameraDriver}.dtbo";
in {
  options.pifinder = {
    cameraType = lib.mkOption {
      type = lib.types.enum [ "imx296" "imx462" "imx477" ];
      default = "imx462";
      description = "Camera sensor type for PiFinder";
    };
    i2cFrequency = lib.mkOption {
      type = lib.types.int;
      default = 10000;
      description = "I2C1 bus clock frequency in Hz (10 kHz for BNO055 IMU)";
    };
  };

  config = {
    # Only include RPi 4B device tree (not CM4 variants)
    hardware.deviceTree.filter = "*rpi-4-b.dtb";
    # Explicit DTB name so extlinux uses FDT instead of FDTDIR
    # (DTBs are in broadcom/ subdirectory, FDTDIR doesn't descend into it)
    hardware.deviceTree.name = "broadcom/bcm2711-rpi-4-b.dtb";

    # I2C enabled (loads i2c-dev module, creates i2c group)
    hardware.i2c.enable = true;

    # Apply all DT overlays via fdtoverlay, bypassing NixOS apply_overlays.py
    # which rejects RPi camera overlays due to compatible string mismatch
    # (overlays declare "brcm,bcm2835" but kernel DTBs use "brcm,bcm2711")
    hardware.deviceTree.package = let
      kernelDtbs = config.hardware.deviceTree.dtbSource;
    in lib.mkForce (pkgs.runCommand "device-tree-with-overlays" {
      nativeBuildInputs = [ pkgs.dtc ];
    } ''
      mkdir -p $out/broadcom
      for dtb in ${kernelDtbs}/broadcom/*rpi-4-b.dtb; do
        fdtoverlay -i "$dtb" \
          -o "$out/broadcom/$(basename $dtb)" \
          ${i2c1Dtbo} ${spi0Dtbo} ${uart3Dtbo} ${pwmDtbo} ${cameraDtbo}
      done
    '');

    # udev rules for hardware access without root
    services.udev.extraRules = ''
      SUBSYSTEM=="spidev", GROUP="spi", MODE="0660"
      SUBSYSTEM=="i2c-dev", GROUP="i2c", MODE="0660"
      SUBSYSTEM=="pwm", GROUP="gpio", MODE="0660"
      SUBSYSTEM=="gpio", GROUP="gpio", MODE="0660"
      KERNEL=="gpiomem", GROUP="gpio", MODE="0660"
      KERNEL=="ttyAMA1", GROUP="dialout", MODE="0660"
      # DMA heap for libcamera/picamera2 (CMA memory allocation)
      SUBSYSTEM=="dma_heap", GROUP="video", MODE="0660"
    '';

    users.users.root.initialPassword = "solveit";
    users.users.pifinder = {
      isNormalUser = true;
      initialPassword = "solveit";
      extraGroups = [ "spi" "i2c" "gpio" "dialout" "video" "networkmanager" "systemd-journal" "input" "kmem" ];
    };
    users.groups = {
      spi = {};
      i2c = {};
      gpio = {};
    };
  };
}
