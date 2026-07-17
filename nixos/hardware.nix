{ config, lib, pkgs, ... }:
let
  cfg = config.pifinder;

  # Camera overlay name mapping. imx462 deliberately uses the imx290 overlay:
  # that is the exact configuration PiFinder ships on Raspbian
  # (switch_camera.py writes "dtoverlay=imx290,clock-frequency=74250000"), so
  # the sony,imx290lqr driver path is field-proven on this sensor. The kernel
  # also ships imx462.dtbo (sony,imx462lqr, dedicated init registers) — an
  # untested-here alternative. The clock-frequency parameter is the part that
  # actually matters; see cameraClockDtbo below.
  cameraDriver = {
    imx296 = "imx296";
    imx462 = "imx290";
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

  # UART3 for the on-board GPS (published as /dev/gpsuart by udev)
  uart3Dtbo = compileOverlay "uart3" ''
    /dts-v1/;
    /plugin/;
    / { compatible = "brcm,bcm2711"; };
    &uart3 { status = "okay"; };
  '';

  # Peripheral I2C (BNO055 IMU, rev-4 BQ25895 charger) as a bit-banged
  # i2c-gpio bus on the standard SDA/SCL pins (GPIO2/GPIO3). The BCM2711
  # hardware I2C block corrupts transfers when a slave stretches the clock
  # (a silicon bug; the BNO055 stretches routinely) — the previous
  # workaround, running &i2c1 at 10 kHz, only lowered the corruption odds
  # while making every IMU transaction ~10x slower. i2c-gpio implements
  # clock stretching per spec at ~60-100 kHz effective. &i2c1 is disabled
  # explicitly so the hardware block never claims the pins; the Python
  # side (PiFinder.i2c_bus.get_i2c) discovers this adapter through sysfs.
  i2cGpioDtbo = compileOverlay "i2c-gpio" ''
    /dts-v1/;
    /plugin/;
    / { compatible = "brcm,bcm2711"; };
    &i2c1 { status = "disabled"; };
    &{/} {
      i2c_gpio: i2c-gpio {
        compatible = "i2c-gpio";
        sda-gpios = <&gpio 2 6>;  /* GPIO_OPEN_DRAIN */
        scl-gpios = <&gpio 3 6>;  /* GPIO_OPEN_DRAIN */
        i2c-gpio,delay-us = <2>;
        #address-cells = <1>;
        #size-cells = <0>;
      };
    };
  '';

  # PWM: GPIO 13 (channel 1) keypad backlight + GPIO 12 (channel 0) rev-4
  # buzzer earcons. Both ALT0 (function 4): GPIO12 = PWM0_0, GPIO13 = PWM0_1.
  # Muxing GPIO12 unconditionally is safe — rev-3 boards leave it unconnected
  # and the sound process only spawns when the rev-4 charger is detected.
  pwmDtbo = compileOverlay "pwm" ''
    /dts-v1/;
    /plugin/;
    / { compatible = "brcm,bcm2711"; };
    &gpio {
      pwm_pins: pwm_pins {
        brcm,pins = <12 13>;
        brcm,function = <4 4>;  /* ALT0 = PWM0_0, PWM0_1 */
      };
    };
    &pwm {
      status = "okay";
      pinctrl-names = "default";
      pinctrl-0 = <&pwm_pins>;
    };
  '';

  # Rev-4 power-off latch (ADR 0007 on main): driving GPIO14 low trips the
  # LTC2954 and cuts power. The kernel's gpio-poweroff handler runs strictly
  # after filesystems are down, and only on a real power-off (reboot takes a
  # different path). Active-low; the board's hardware pull-up on GPIO14 holds
  # power on until the handler fires. Deliberately unconditional across
  # revisions: on rev-3 GPIO14-low does nothing electrically — the only effect
  # is a cosmetic kernel WARN + ~3s wait at halt.
  gpioPoweroffDtbo = compileOverlay "gpio-poweroff" ''
    /dts-v1/;
    /plugin/;
    / { compatible = "brcm,bcm2711"; };
    &{/} {
      power_ctrl: power_ctrl {
        compatible = "gpio-poweroff";
        gpios = <&gpio 14 1>;  /* GPIO_ACTIVE_LOW */
        timeout-ms = <3000>;
      };
    };
  '';

  # Camera overlay from kernel's DTB overlays directory
  cameraDtbo = "${config.boot.kernelPackages.kernel}/dtbs/overlays/${cameraDriver}.dtbo";

  # PiFinder's imx462 module has a 74.25 MHz oscillator, but the kernel's
  # imx290/imx462 overlays default the xclk to 37.125 MHz. Raspbian fixes this
  # with the overlay parameter "clock-frequency=74250000"; fdtoverlay cannot
  # apply overlay parameters (__overrides__), so without this the default
  # sneaks through and the driver programs INCKSEL/PLL for the wrong xclk —
  # the sensor enumerates on I2C but never delivers frames and libcamera
  # reports "Camera frontend has timed out" with an empty kernel log.
  # Override both places the Raspbian parameter writes: the fixed-clock node
  # (the driver's clk_set_rate must match its rate) and the sensor node
  # property (the driver selects the INCKSEL register set from it). Must be
  # applied after cameraDtbo: &cam_node is defined by the camera overlay and
  # resolves from its merged symbols.
  cameraClockDtbo = compileOverlay "imx462-xclk" ''
    /dts-v1/;
    /plugin/;
    / { compatible = "brcm,bcm2711"; };
    &cam1_clk { clock-frequency = <74250000>; };
    &cam_node { clock-frequency = <74250000>; };
  '';
in {
  options.pifinder = {
    cameraType = lib.mkOption {
      type = lib.types.enum [ "imx296" "imx462" "imx477" ];
      default = "imx462";
      description = "Camera sensor type for PiFinder";
    };
  };

  config = {
    # BCM2711 device trees: Pi 4B (PiFinder rev 3) and CM4 (PiFinder v4).
    # The deviceTree.package override below processes exactly these two.
    hardware.deviceTree.filter = "bcm2711-rpi-*.dtb";
    # No explicit deviceTree.name: extlinux then emits FDTDIR instead of FDT,
    # and u-boot appends its board-detected ${fdtfile} to it — which on 64-bit
    # u-boot already carries the broadcom/ subdirectory prefix (DTB_DIR in
    # board/raspberrypi/rpi/rpi.c). One image thus boots the matching DTB on
    # both the 4B and the CM4. Rollback if a board fails to pick its DTB:
    # set hardware.deviceTree.name = "broadcom/<board>.dtb" to force FDT.
    hardware.deviceTree.name = null;

    # Firmware: the nixos-hardware Pi 4 module enables the full redistributable
    # set — linux-firmware alone is ~723MB uncompressed, 40% of the migration
    # tarball, for hardware this board doesn't have. The Pi 4 needs only the
    # Broadcom wifi/BT blobs (~10MB). Boot firmware (start.elf etc.) is
    # separate and unaffected (populateFirmwareCommands).
    hardware.enableRedistributableFirmware = lib.mkForce false;
    hardware.firmware = [ pkgs.raspberrypiWirelessFirmware ];

    # I2C enabled (loads i2c-dev module, creates i2c group)
    hardware.i2c.enable = true;
    # The bit-banged bus driver (DT modalias autoload also works when built
    # as a module; listing it here makes the dependency explicit)
    boot.kernelModules = [ "i2c-gpio" ];

    # GPIO14 is the rev-4 power-off kill line (gpio-poweroff overlay above) —
    # its default function is UART0 TXD, so nothing may drive serial console
    # bytes onto it (ADR 0007). No console= kernel param points there, and this
    # keeps a getty from ever claiming the port.
    systemd.services."serial-getty@ttyAMA0".enable = false;

    # Apply all DT overlays via fdtoverlay, bypassing NixOS apply_overlays.py
    # which rejects RPi camera overlays due to compatible string mismatch
    # (overlays declare "brcm,bcm2835" but kernel DTBs use "brcm,bcm2711")
    hardware.deviceTree.package = let
      kernelDtbs = config.hardware.deviceTree.dtbSource;
    in lib.mkForce (pkgs.runCommand "device-tree-with-overlays" {
      nativeBuildInputs = [ pkgs.dtc ];
    } ''
      mkdir -p $out/broadcom
      for dtb in ${kernelDtbs}/broadcom/bcm2711-rpi-4-b.dtb \
                 ${kernelDtbs}/broadcom/bcm2711-rpi-cm4.dtb; do
        fdtoverlay -i "$dtb" \
          -o "$out/broadcom/$(basename $dtb)" \
          ${i2cGpioDtbo} ${spi0Dtbo} ${uart3Dtbo} ${pwmDtbo} ${gpioPoweroffDtbo} ${cameraDtbo} \
          ${lib.optionalString (cfg.cameraType == "imx462") cameraClockDtbo}
      done
    '');

    # udev rules for hardware access without root
    services.udev.extraRules = ''
      SUBSYSTEM=="spidev", GROUP="spi", MODE="0660"
      SUBSYSTEM=="i2c-dev", GROUP="i2c", MODE="0660"
      SUBSYSTEM=="pwm", GROUP="gpio", MODE="0660"
      SUBSYSTEM=="gpio", GROUP="gpio", MODE="0660"
      KERNEL=="gpiomem", GROUP="gpio", MODE="0660"
      # On-board GPS UART (uart3, fe201600 on BCM2711): the kernel's ttyAMA
      # numbering is not stable across versions, so match the DT node and
      # publish a fixed name for gpsd to open.
      SUBSYSTEM=="tty", KERNELS=="fe201600.serial", SYMLINK+="gpsuart", GROUP="dialout", MODE="0660", TAG+="systemd", ENV{SYSTEMD_WANTS}+="gpsd-add-uart.service"
      # DMA heap for libcamera/picamera2 (CMA memory allocation)
      SUBSYSTEM=="dma_heap", GROUP="video", MODE="0660"
    '';

    # Deterministic root password (sha-512 crypt of "solveit"), enforced on
    # every activation — unlike initialPassword, which only applies at account
    # creation and drifts if changed at runtime. Test-device convenience; the
    # hash lives in the world-readable store, which is fine for a known cred.
    users.users.root.hashedPassword =
      "$6$caME5a7TbhnPfrV2$sXHx/OuQCaRkjCG/Lba8vxL5R8.SgD72YHKWzHwDVj9CfDgz1xJ766ht0VCB18Q/igzceaoQM8fwgYNj2ygap/";
    users.users.pifinder = {
      isNormalUser = true;
      # MUST stay initialPassword (not hashedPassword): the web UI changes this
      # password at runtime via `sudo chpasswd` (sys_utils.change_password).
      # initialPassword applies only at account creation, so that change
      # persists; hashedPassword would re-enforce "solveit" on every activation
      # and silently revert the user's password on the next upgrade.
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
