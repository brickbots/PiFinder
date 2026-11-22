# Minimal AP fallback for the migration image, which has no Python
# environment. The full system runs pifinder-net-policy (libnm daemon,
# services.nix) instead; this is a stripped-down shell version of the same
# priority — wired > wifi client > AP — good enough for the short-lived
# bootstrap system whose only job is staying reachable until first boot.
{ pkgs, ... }:
{
  systemd.services.pifinder-wifi-fallback = {
    description = "Bring up PiFinder AP when offline (migration image)";
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

      # Wired connectivity is sufficient — never start the AP over it.
      eth_up() {
        nmcli -t -f TYPE,STATE device | grep -q '^ethernet:connected'
      }
      # A wifi CLIENT connection. Matching the device state alone would
      # count the AP itself as "connected" and make the AP sticky.
      wifi_client_up() {
        nmcli -t -f TYPE,NAME connection show --active \
          | grep '^802-11-wireless:' \
          | grep -qvx '802-11-wireless:PiFinder-AP'
      }

      # Give NetworkManager a grace period to land on something better.
      for _ in $(seq 1 45); do
        if eth_up || wifi_client_up; then
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
