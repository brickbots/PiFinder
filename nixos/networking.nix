{ config, lib, pkgs, ... }:
{
  networking = {
    hostName = "pifinder";
    networkmanager.enable = true;
    wireless.enable = false; # NetworkManager handles WiFi
    firewall = {
      checkReversePath = "loose";   # Allow multi-interface (WiFi + ethernet) on same subnet
      allowedUDPPorts = [ 53 67 ];  # DNS + DHCP for AP mode
      allowedTCPPorts = [ 80 ];     # PiFinder web UI (other ports via service openFirewall)
    };
  };

  # Robust time sync for the RTC-less Pi: NTP= servers are always tried (and
  # combined with any per-interface/DHCP servers), so a dead DHCP-advertised
  # NTP server can't block the clock. FallbackNTP alone is skipped whenever a
  # per-interface server is known — too fragile to rely on for first-boot
  # migration, which gates the binary-cache fetch on a synchronized clock.
  services.timesyncd.servers = [
    "0.pool.ntp.org"
    "1.pool.ntp.org"
    "2.pool.ntp.org"
    "3.pool.ntp.org"
  ];

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

  # AP fallback / persistence. The PiFinder-AP profile has a low autoconnect
  # priority, so NetworkManager prefers a known client network when one is
  # reachable. This service makes the AP a reliable fallback: it brings the AP
  # up when no client connects within a grace period (so a device with a saved
  # but-unreachable network is still reachable), and when the user has forced AP
  # mode in the UI (persisted to PiFinder_data/wifi_mode).
  systemd.services.pifinder-wifi-fallback = {
    description = "Bring up PiFinder AP when no WiFi client is connected";
    after = [ "NetworkManager.service" ];
    wants = [ "NetworkManager.service" ];
    wantedBy = [ "multi-user.target" ];
    path = [ pkgs.networkmanager pkgs.coreutils pkgs.gnugrep ];
    serviceConfig.Type = "oneshot";
    script = ''
      modefile=/home/pifinder/PiFinder_data/wifi_mode

      if [ -r "$modefile" ] && [ "$(cat "$modefile")" = "AP" ]; then
        nmcli connection up PiFinder-AP || true
        exit 0
      fi

      # Give NetworkManager up to 45s to join a known client network.
      for _ in $(seq 1 45); do
        if nmcli -t -f TYPE,STATE device | grep -q '^wifi:connected'; then
          exit 0
        fi
        sleep 1
      done

      nmcli connection up PiFinder-AP || true
    '';
  };

  systemd.timers.pifinder-wifi-fallback = {
    description = "Periodically ensure WiFi falls back to AP when offline";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "30s";
      OnUnitActiveSec = "120s";
    };
  };
}
