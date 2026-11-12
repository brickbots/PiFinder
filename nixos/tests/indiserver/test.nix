# VM test of nixos/indi.nix:
# - indiserver starts with no driver, and a "start" line in the FIFO, written
#   by the pifinder user as PiFinder does, loads the telescope simulator.
# - USB contention: ModemManager is off, and the udev rule keeps gpsd hotplug
#   off a generic USB-serial bridge unless /var/lib/pifinder/usb/generic-gps
#   exists (GPS Type "GPSD (generic)"). QEMU emulates only an FTDI bridge,
#   which gpsd does not claim, so a test rule claims it the way
#   25-gpsd.rules claims a CP210x, and the FTDI vendor ID joins
#   pifinder.mountUsbBridges.
#
#   nix build -L .#checks.x86_64-linux.indiserver
{ pkgs, ... }:
{
  name = "indiserver";

  nodes.machine = {
    imports = [ ../../indi.nix ];
    users.users.pifinder = {
      isNormalUser = true;
      extraGroups = [ "dialout" ];
    };

    pifinder.mountUsbBridges = [ "10c4" "0557" "067b" "0403" ];
    virtualisation.qemu.options = [
      "-device qemu-xhci,id=xhci"
      "-chardev null,id=usbserial"
      "-device usb-serial,bus=xhci.0,chardev=usbserial,always-plugged=on"
    ];

    # gpsd as on the device: its own units, socket activation, hotplug.
    systemd.packages = [ pkgs.gpsd ];
    systemd.sockets.gpsd.wantedBy = [ "sockets.target" ];
    users.users.gpsd = {
      isSystemUser = true;
      group = "gpsd";
    };
    users.groups.gpsd = { };
    environment.systemPackages = [ pkgs.gpsd ];
    services.udev.packages = [
      (pkgs.writeTextDir "lib/udev/rules.d/25-test-gpsd-ftdi.rules" ''
        SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", SYMLINK+="gps%n", TAG+="systemd", ENV{SYSTEMD_WANTS}+="gpsdctl@%k.service"
      '')
    ];
  };

  testScript = ''
    machine.wait_for_unit("indiserver.service")
    machine.wait_for_open_port(7624)
    machine.succeed("test -p /run/indi/fifo")
    print(machine.succeed("stat -c '%U %a' /run/indi /run/indi/fifo"))

    # No driver yet.
    machine.fail("indi_getprop -t 2 -p 7624 'Telescope Simulator.CONNECTION.*'")

    machine.succeed(
        "su pifinder -c "
        "'echo start indi_simulator_telescope -n \\\"Telescope Simulator\\\" "
        "> /run/indi/fifo'"
    )
    machine.wait_until_succeeds(
        "indi_getprop -t 2 -p 7624 'Telescope Simulator.CONNECTION.*'", timeout=30
    )
    print(machine.succeed("indi_getprop -t 2 -p 7624 'Telescope Simulator.DRIVER_INFO.*'"))

    # The PiFinder service gets the driver XML directory.
    print(machine.succeed("systemctl show -p Environment pifinder"))

    # USB contention.
    machine.fail("systemctl cat ModemManager.service")
    machine.wait_until_succeeds("test -e /dev/ttyUSB0")

    def wants():
        out = machine.succeed(
            "udevadm test --action=add /sys/class/tty/ttyUSB0 2>&1 "
            "| grep -E '^[[:space:]]*SYSTEMD_WANTS=' || true"
        )
        print("udev:", out.strip())
        return out

    # Default: the bridge is for a mount, gpsd hotplug stays off it.
    assert "gpsdctl@" not in wants()
    print(machine.succeed("stat -c '%U' /var/lib/pifinder/usb"))
    # GPS Type "GPSD (generic)": PiFinder (as pifinder) creates the file,
    # and gpsd takes the bridge again.
    machine.succeed("su pifinder -c 'touch /var/lib/pifinder/usb/generic-gps'")
    assert "gpsdctl@ttyUSB0" in wants()
    machine.succeed("rm /var/lib/pifinder/usb/generic-gps")
    assert "gpsdctl@" not in wants()
  '';
}
