# INDI with the mount drivers PiFinder uses: core INDI (OnStep/OnStepX,
# LX200, SynScan, iOptron, Celestron, PMC-8, AM5 and more) and the 3rd-party
# mount drivers that core INDI does not have. No camera drivers.
# nixos/indi.nix installs it; the flake exports it as packages.<system>.indi,
# so the tests run the same INDI as the device.
{ pkgs }:
pkgs.indi-with-drivers.override {
  extraDrivers = with pkgs.indi-3rdparty; [
    indi-eqmod
    indi-celestronaux
    indi-starbook
    indi-starbook-ten
  ];
}
