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
      # Never self-start: NetworkManager would activate the AP instantly at
      # boot (own radio, no scan needed) and win the race against a client
      # network that still has to scan + associate, then stay on it. The AP is
      # brought up only on demand by pifinder-wifi-fallback below.
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

  # AP fallback / persistence. The PiFinder-AP profile has autoconnect disabled,
  # so NetworkManager joins a known client network when one is reachable and
  # never self-starts the AP. This service makes the AP a reliable fallback: it
  # brings the AP up when no client connects within a grace period (so a device
  # with a saved but-unreachable network is still reachable), and when the user
  # has forced AP mode in the UI (persisted to PiFinder_data/wifi_mode).
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

  # ---------------------------------------------------------------------------
  # Avahi/mDNS for hostname discovery (<host>.local). It lives in this shared
  # networking module on purpose: BOTH the running system (commonModules) and
  # the migration build (migrationModules) import networking.nix, whereas
  # services.nix and device.nix are each only in one of those — so avahi must
  # not live in either alone or one system ends up with no mDNS at all.
  # ---------------------------------------------------------------------------
  services.avahi = {
    enable = true;
    nssmdns4 = true;
    publish = {
      enable = true;
      addresses = true;
      domain = true;
      workstation = true;
    };
  };

  systemd.services.avahi-daemon.serviceConfig.ExecStartPre =
    "${pkgs.coreutils}/bin/rm -f /run/avahi-daemon/pid";

  # Apply user-chosen hostname from PiFinder_data (survives NixOS rebuilds),
  # overriding networking.hostName above.
  systemd.services.pifinder-hostname = {
    description = "Apply PiFinder custom hostname";
    after = [ "avahi-daemon.service" ];
    wants = [ "avahi-daemon.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = pkgs.writeShellScript "apply-hostname" ''
        f=/home/pifinder/PiFinder_data/hostname
        [ -f "$f" ] || exit 0
        name=$(cat "$f")
        [ -n "$name" ] || exit 0
        /run/current-system/sw/bin/hostname "$name"
        /run/current-system/sw/bin/avahi-set-host-name "$name" || \
          /run/current-system/sw/bin/systemctl restart avahi-daemon.service
      '';
    };
  };

  # Avahi binds whatever interfaces are up when it starts. A PiFinder has both
  # the wlan0 AP (up fast) and the DHCP'd LAN end0 (up slow); avahi frequently
  # starts before the LAN and then never re-binds it, leaving the unit
  # unreachable as <host>.local over ethernet. Re-scan avahi whenever
  # NetworkManager activates a connection so it always reflects current links.
  # NetworkManager must not manage the hostname, or it resets it to the static
  # "pifinder" (networking.hostName) and undoes pifinder-hostname's value.
  networking.networkmanager.settings.main."hostname-mode" = "none";

  networking.networkmanager.dispatcherScripts = [{
    source = pkgs.writeShellScript "avahi-rescan-on-net" ''
      case "$2" in
        up|connectivity-change)
          # Re-scan avahi onto the now-up link (it misses the slow DHCP'd LAN at
          # boot). NixOS bakes host-name=<static> into avahi's config, so the
          # restart reverts the published name to "pifinder" — re-assert the
          # user hostname (system + avahi runtime) afterwards; that sticks.
          f=/home/pifinder/PiFinder_data/hostname
          name=""
          if [ -s "$f" ]; then
            name=$(cat "$f")
            /run/current-system/sw/bin/hostname "$name" 2>/dev/null || true
          fi
          ${pkgs.systemd}/bin/systemctl try-restart avahi-daemon.service || true
          [ -n "$name" ] && /run/current-system/sw/bin/avahi-set-host-name "$name" 2>/dev/null || true
          ;;
      esac
    '';
  }];
}
