# VM test of the indiserver service (nixos/indi.nix): it starts with no
# driver, and a "start" line in the FIFO, written by the pifinder user as
# PiFinder does, loads the telescope simulator.
#
#   nix build -L .#checks.x86_64-linux.indiserver
{ ... }:
{
  name = "indiserver";

  nodes.machine = {
    imports = [ ../../indi.nix ];
    users.users.pifinder = {
      isNormalUser = true;
      extraGroups = [ "dialout" ];
    };
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
  '';
}
