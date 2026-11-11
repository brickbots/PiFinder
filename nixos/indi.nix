{ pkgs, lib, ... }:
let
  # Core INDI has the mount drivers for OnStep/OnStepX, LX200, SynScan,
  # iOptron, Celestron, PMC-8, AM5 and more. The 3rd-party set adds the
  # common mounts that core INDI does not have. No camera drivers.
  indi = pkgs.indi-with-drivers.override {
    extraDrivers = with pkgs.indi-3rdparty; [
      indi-eqmod
      indi-celestronaux
      indi-starbook
      indi-starbook-ten
    ];
  };
in
{
  # ---------------------------------------------------------------------------
  # INDI server for mount control
  # ---------------------------------------------------------------------------
  # indiserver runs with no driver. PiFinder starts the mount driver that the
  # user selects by writing "start <driver>" to the FIFO, and stops it with
  # "stop <driver>", so a driver change needs no restart of this service.
  # Port 7624 is not in the firewall, so only local clients can connect.
  environment.systemPackages = [ indi ];

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

  # PiFinder reads the mount driver list from the INDI driver XML files.
  systemd.services.pifinder.environment = {
    INDI_DATA_DIR = "${indi}/share/indi";
    INDI_FIFO = "/run/indi/fifo";
  };
}
