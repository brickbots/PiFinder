{ config, lib, pkgs, ... }:
{
  networking = {
    hostName = "pifinder";
    networkmanager.enable = true;
    wireless.enable = false; # NetworkManager handles WiFi
  };

  # Wired ethernet with DHCP (autoconnect)
  environment.etc."NetworkManager/system-connections/Wired.nmconnection" = {
    text = ''
      [connection]
      id=Wired
      type=ethernet
      autoconnect=true

      [ipv4]
      method=auto

      [ipv6]
      method=auto
    '';
    mode = "0600";
  };

  # Pre-configured AP profile (activated on demand via nmcli)
  environment.etc."NetworkManager/system-connections/PiFinder-AP.nmconnection" = {
    text = ''
      [connection]
      id=PiFinder-AP
      type=wifi
      autoconnect=false

      [wifi]
      mode=ap
      ssid=PiFinderAP
      band=bg
      channel=7

      [ipv4]
      method=shared
      address1=10.10.10.1/24

      [ipv6]
      method=disabled
    '';
    mode = "0600";
  };
}
