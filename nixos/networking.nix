{ config, lib, pkgs, ... }:
{
  networking = {
    hostName = "pifinder";
    networkmanager.enable = true;
    wireless.enable = false; # NetworkManager handles WiFi
    firewall = {
      allowedUDPPorts = [ 53 67 ];  # DNS + DHCP for AP mode
      allowedTCPPorts = [ 80 ];     # PiFinder web UI (other ports via service openFirewall)
    };
  };

  # dnsmasq for NetworkManager AP shared mode (DHCP for AP clients)
  services.dnsmasq.enable = false;  # NM manages its own dnsmasq instance
  environment.systemPackages = [ pkgs.dnsmasq ];

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

  # Policy routing: when ethernet and WiFi are on the same subnet, the kernel
  # sends all replies via ethernet (lower metric), breaking TCP on the WiFi IP.
  # This dispatcher adds a policy route so WiFi-sourced replies go out WiFi.
  environment.etc."NetworkManager/dispatcher.d/50-policy-route" = {
    text = ''
      #!/bin/sh
      [ "$1" = "wlan0" ] || [ "$1" = "end0" ] || exit 0
      case "$2" in up|down|dhcp4-change) ;; *) exit 0 ;; esac

      ip rule del from all table 100 2>/dev/null || true
      ip route flush table 100 2>/dev/null || true

      WLAN_CIDR=$(ip -4 -o addr show wlan0 2>/dev/null | awk '{print $4}')
      [ -z "$WLAN_CIDR" ] && exit 0
      WLAN_IP=''${WLAN_CIDR%%/*}
      WLAN_GW=$(ip route show dev wlan0 default 2>/dev/null | awk '{print $3}' | head -1)
      [ -z "$WLAN_IP" ] || [ -z "$WLAN_GW" ] && exit 0
      WLAN_NET=$(python3 -c "import ipaddress; print(ipaddress.ip_interface('$WLAN_CIDR').network)")

      ip route add "$WLAN_NET" dev wlan0 src "$WLAN_IP" table 100
      ip route add default via "$WLAN_GW" dev wlan0 table 100
      ip rule add from "$WLAN_IP" table 100 priority 100
    '';
    mode = "0755";
  };

  # Pre-configured AP profile (activated on demand via nmcli)
  environment.etc."NetworkManager/system-connections/PiFinder-AP.nmconnection" = {
    text = ''
      [connection]
      id=PiFinder-AP
      type=wifi
      autoconnect=true
      autoconnect-priority=-1

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
