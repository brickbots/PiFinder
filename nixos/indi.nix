{ config, pkgs, lib, ... }:
let
  indi = import ./pkgs/indi.nix { inherit pkgs; };
in
{
  options.pifinder.mountUsbBridges = lib.mkOption {
    type = lib.types.listOf lib.types.str;
    # gpsd hotplug claims these generic USB-serial bridges (25-gpsd.rules),
    # and mount controllers use them too: CP210x (ESP32 boards with OnStepX,
    # many mount cables), ATEN UC-232A, and a Prolific variant.
    default = [ "10c4" "0557" "067b" ];
    description = "USB vendor IDs that gpsd takes only with GPS Type GPSD (generic).";
  };

  config = {
    # ---------------------------------------------------------------------------
    # INDI server for mount control
    # ---------------------------------------------------------------------------
    # indiserver runs with no driver. PiFinder starts the mount driver that the
    # user selects by writing "start <driver>" to the FIFO, and stops it with
    # "stop <driver>", so a driver change needs no restart of this service.
    # Port 7624 is not in the firewall, so only local clients can connect.
    environment.systemPackages = [ indi ];

    # USB serial contention. Two services open a new USB serial port:
    # - ModemManager probes it with AT commands. PiFinder has no modem, and the
    #   probe can upset a mount controller, so ModemManager is off.
    # - gpsd hotplug (25-gpsd.rules) opens the generic USB-serial bridges in
    #   pifinder.mountUsbBridges, and mount controllers use them too. This
    #   rule keeps gpsd off them, so it never probes a mount. With GPS Type
    #   "GPSD (generic)" PiFinder creates /var/lib/pifinder/usb/generic-gps,
    #   and the bridges go to gpsd again, for a USB GPS dongle. GPS-vendor
    #   devices (u-blox, Garmin and others) always go to gpsd. The file
    #   persists, so the rule also holds at boot, before PiFinder starts.
    networking.modemmanager.enable = false;
    services.udev.extraRules = ''
      SUBSYSTEM=="tty", ATTRS{idVendor}=="${lib.concatStringsSep "|" config.pifinder.mountUsbBridges}", TEST!="/var/lib/pifinder/usb/generic-gps", ENV{SYSTEMD_WANTS}=""
    '';
    systemd.tmpfiles.rules = [ "d /var/lib/pifinder/usb 0755 pifinder users -" ];

    systemd.services.indiserver = {
      description = "INDI server for mount control";
      wantedBy = [ "multi-user.target" ];
      # indiserver runs a driver by its name from PATH.
      path = [ indi ];
      serviceConfig = {
        User = "pifinder";
        # Mount drivers open USB serial ports.
        SupplementaryGroups = [ "dialout" ];
        RuntimeDirectory = "indi";
        ExecStartPre = "${pkgs.coreutils}/bin/mkfifo -m 0600 /run/indi/fifo";
        ExecStart = "${indi}/bin/indiserver -p 7624 -f /run/indi/fifo";
        Restart = "always";
        RestartSec = 5;
      };
    };

    # PiFinder reads the mount driver list from the INDI driver XML files, and
    # looks for the USB bridges when GPS Type changes (usb_gps.py).
    # The mount process starts the driver through the FIFO at boot.
    systemd.services.pifinder.wants = [ "indiserver.service" ];
    systemd.services.pifinder.after = [ "indiserver.service" ];
    systemd.services.pifinder.environment = {
      INDI_DATA_DIR = "${indi}/share/indi";
      INDI_FIFO = "/run/indi/fifo";
      PIFINDER_MOUNT_USB_BRIDGES = lib.concatStringsSep " " config.pifinder.mountUsbBridges;
    };
  };
}
