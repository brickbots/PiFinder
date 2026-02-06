{ config, lib, pkgs, ... }:
let
  cfg = config.pifinder;

  # Camera driver name mapping
  cameraDriver = {
    imx296 = "imx296";
    imx462 = "imx290";  # imx462 uses imx290 driver
    imx477 = "imx477";
  }.${cfg.cameraType};
in {
  options.pifinder = {
    cameraType = lib.mkOption {
      type = lib.types.enum [ "imx296" "imx462" "imx477" ];
      default = "imx296";
      description = "Camera sensor type for PiFinder";
    };

    runtimeCameraSelection = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Enable runtime camera selection via /boot/camera.txt.
        When true, camera overlay is loaded via config.txt include (SD card).
        When false, camera overlay is baked into device tree (netboot).
      '';
    };
  };

  config = {
    # Only include RPi 4B device tree (not CM4 variants)
    hardware.deviceTree.filter = "*rpi-4-b.dtb";

    # I2C1 (ARM bus) at 10 kHz for BNO055 IMU
    hardware.raspberry-pi."4".i2c1 = {
      enable = true;
      frequency = 10000;
    };

    hardware.deviceTree.overlays = let
      # SPI0 — no nixos-hardware option, use custom overlay
      spi0Overlay = {
        name = "spi0-overlay";
        dtsText = ''
          /dts-v1/;
          /plugin/;
          / { compatible = "brcm,bcm2711"; };
          &spi0 { status = "okay"; };
        '';
      };

      # UART3 for GPS on /dev/ttyAMA1
      uart3Overlay = {
        name = "uart3-overlay";
        dtsText = ''
          /dts-v1/;
          /plugin/;
          / { compatible = "brcm,bcm2711"; };
          &uart3 { status = "okay"; };
        '';
      };

      # PWM on GPIO 13 (function 4) for keypad backlight
      # nixos-hardware pwm0 is hardcoded to GPIO 18, so use custom overlay
      pwmOverlay = {
        name = "pwm-pin13-overlay";
        dtsText = ''
          /dts-v1/;
          /plugin/;
          / { compatible = "brcm,bcm2711"; };
          &gpio {
            pwm_pins: pwm_pins {
              brcm,pins = <13>;
              brcm,function = <4>;
            };
          };
          &pwm { status = "okay"; };
        '';
      };

      # Camera dtoverlay — only bake into device tree when NOT using runtime selection
      # For SD cards (runtimeCameraSelection=true), overlay is loaded via config.txt
      cameraOverlay = {
        name = "${cameraDriver}-camera";
        dtboFile = "${pkgs.raspberrypifw}/share/raspberrypi/boot/overlays/${cameraDriver}.dtbo";
      };
    in [
      spi0Overlay
      uart3Overlay
      pwmOverlay
    ] ++ lib.optionals (!cfg.runtimeCameraSelection) [
      cameraOverlay
    ];

    # Runtime camera selection: create /boot/camera.txt with default overlay
    # User can edit this file and reboot to switch cameras
    environment.etc."camera.txt.default" = lib.mkIf cfg.runtimeCameraSelection {
      text = ''
        # Camera overlay - edit and reboot to change camera
        # Options: imx296, imx290 (for imx462), imx477
        dtoverlay=${cameraDriver}
      '';
    };

    # udev rules for hardware access without root
    services.udev.extraRules = ''
      SUBSYSTEM=="spidev", GROUP="spi", MODE="0660"
      SUBSYSTEM=="i2c-dev", GROUP="i2c", MODE="0660"
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
