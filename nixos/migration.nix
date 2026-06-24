{ config, lib, pkgs, ... }:
let
  boot-splash = import ./pkgs/boot-splash.nix { inherit pkgs; };
in {
  options.pifinder = {
    devMode = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable development mode (NFS netboot support, etc.)";
    };
  };

  config = {
  # ---------------------------------------------------------------------------
  # Minimal system packages for migration troubleshooting
  # ---------------------------------------------------------------------------
  environment.systemPackages = with pkgs; [
    vim
    htop
    e2fsprogs
    dosfstools
    parted
    file
    curl
  ];

  # ---------------------------------------------------------------------------
  # Binary substituters — Pi downloads pre-built paths, never compiles.
  # Two Attic caches on cache.pifinder.eu (ADR 0004): pifinder-release (retained
  # release closures) and pifinder (dev/nightly). The first-boot download below
  # pulls whichever closure pifinder-build.json points at.
  # ---------------------------------------------------------------------------
  nix.settings = {
    experimental-features = [ "nix-command" "flakes" ];
    substituters = [
      "https://cache.pifinder.eu/pifinder-release"
      "https://cache.pifinder.eu/pifinder"
      "https://cache.nixos.org"
    ];
    trusted-public-keys = [
      # NOTE: add pifinder-release's real key here once that cache is
      # provisioned (same value as nixos/services.nix). Never ship a
      # placeholder — invalid base64 aborts every nix operation.
      "pifinder:8UU/O3oLkaJHHUyqEcPGl+9F1m4MqDca39Ewl49jBmE="
      "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
    ];
  };

  # Don't pull nixpkgs source into closure (~186 MB)
  nix.channel.enable = false;
  nix.registry = lib.mkForce {};
  nix.nixPath = lib.mkForce [];

  # nixos-rebuild-ng pulls in Python 3.13 (~110 MB) — not needed for migration
  system.disableInstallerTools = true;

  # Perl is included by default (~59 MB) — not needed for migration
  environment.defaultPackages = lib.mkForce [];

  # Strip NetworkManager VPN plugins (openconnect/stoken/gtk3 deps)
  networking.networkmanager.plugins = lib.mkForce [];

  # ---------------------------------------------------------------------------
  # SD card optimizations
  # ---------------------------------------------------------------------------
  boot.loader.generic-extlinux-compatible.configurationLimit = 2;

  nix.gc = {
    automatic = true;
    dates = "weekly";
    options = "--delete-older-than 3d";
  };
  nix.settings.auto-optimise-store = true;

  boot.tmp.useTmpfs = true;
  boot.tmp.tmpfsSize = "200M";

  services.journald.extraConfig = ''
    Storage=volatile
    RuntimeMaxUse=50M
  '';

  zramSwap = {
    enable = true;
    memoryPercent = 50;
  };

  fileSystems."/" = lib.mkDefault {
    device = "/dev/disk/by-label/NIXOS_SD";
    fsType = "ext4";
    options = [ "noatime" "nodiratime" ];
  };

  # ---------------------------------------------------------------------------
  # Nix DB registration (first boot after migration)
  # ---------------------------------------------------------------------------
  systemd.services.nix-path-registration = {
    description = "Load Nix store path registration from migration";
    after = [ "local-fs.target" ];
    before = [ "nix-daemon.service" ];
    wantedBy = [ "multi-user.target" ];
    unitConfig.ConditionPathExists = "/nix-path-registration";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    path = with pkgs; [ nix coreutils ];
    script = ''
      nix-store --load-db < /nix-path-registration
      rm /nix-path-registration
    '';
  };

  # ---------------------------------------------------------------------------
  # First boot: download full PiFinder system from the binary cache and switch
  # ---------------------------------------------------------------------------
  systemd.services.pifinder-first-boot = {
    description = "Download full PiFinder NixOS system from the binary cache";
    # time-sync.target ordering pairs with the explicit clock-wait in the
    # script below — the Pi has no RTC, and TLS to the binary cache fails
    # while the clock is still in the past.
    after = [ "network-online.target" "time-sync.target" "nix-path-registration.service" "nix-daemon.service" ];
    wants = [ "time-sync.target" ];
    requires = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    unitConfig.ConditionPathExists = "/var/lib/pifinder/first-boot-target";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "30min";
    };
    path = with pkgs; [ nix coreutils systemd curl jq gnugrep ];
    script = ''
      set -euo pipefail

      # Real-progress splash on the OLED, fed via a progress file (0-100).
      PROGRESS_FILE=/run/pifinder-boot-progress
      echo 0 > "$PROGRESS_FILE"
      ${boot-splash}/bin/boot-splash --progress "$PROGRESS_FILE" &
      SPLASH_PID=$!
      trap 'kill $SPLASH_PID 2>/dev/null || true' EXIT

      # Try fetching latest store path from GitHub, fall back to baked-in file
      BUILD_JSON_URL="https://raw.githubusercontent.com/mrosseel/PiFinder/nixos/pifinder-build.json"
      STORE_PATH=""
      if REMOTE_JSON=$(curl -sf --max-time 15 "$BUILD_JSON_URL" 2>/dev/null); then
        STORE_PATH=$(echo "$REMOTE_JSON" | jq -r '.store_path // empty')
        if [ -n "$STORE_PATH" ]; then
          echo "Using store path from GitHub: $STORE_PATH"
        fi
      fi
      if [ -z "$STORE_PATH" ] || [[ "$STORE_PATH" != /nix/store/* ]]; then
        echo "Remote fetch failed or invalid, falling back to baked-in target"
        STORE_PATH=$(cat /var/lib/pifinder/first-boot-target)
      fi
      if [ -z "$STORE_PATH" ] || [[ "$STORE_PATH" != /nix/store/* ]]; then
        echo "ERROR: No valid store path found"
        exit 1
      fi

      # The Pi has no RTC: at cold boot the clock starts in the past, so TLS
      # validation against the binary cache fails ("certificate is not yet
      # valid") and the download aborts. Wait for timesyncd to fix the clock.
      echo "Waiting for clock synchronization..."
      for _ in $(seq 1 120); do
        [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = yes ] && break
        [ -e /run/systemd/timesync/synchronized ] && break
        sleep 1
      done
      echo "Clock: $(date -u)"

      # First-boot fetches the whole system, so per-path byte sizing would mean
      # tens of thousands of cache lookups — too slow. Count the paths to fetch
      # (one dry-run, timeout-bounded so it can't hang) and show a path-count
      # percentage on the splash. set +e keeps it advisory — never aborts.
      echo "Computing download size..."
      set +e
      TOTAL_PATHS=$(timeout 120 nix-store --realise --dry-run "$STORE_PATH" 2>&1 | grep -c '^  /nix/store/')
      case "$TOTAL_PATHS" in ''|*[!0-9]*) TOTAL_PATHS=0 ;; esac
      set -e
      echo "Downloading full PiFinder system: $STORE_PATH ($TOTAL_PATHS paths)"

      COPIED=0
      nix build "$STORE_PATH" --max-jobs 0 2>&1 | while IFS= read -r line; do
        echo "$line"
        case "$line" in
          *"copying path "*)
            COPIED=$((COPIED + 1))
            [ "$TOTAL_PATHS" -gt 0 ] && echo "$((COPIED * 100 / TOTAL_PATHS))" > "$PROGRESS_FILE"
            ;;
        esac
      done
      echo 100 > "$PROGRESS_FILE"

      echo "Setting system profile..."
      nix-env -p /nix/var/nix/profiles/system --set "$STORE_PATH"

      echo "Configuring bootloader..."
      "$STORE_PATH/bin/switch-to-configuration" boot

      echo "Removing first-boot trigger..."
      rm /var/lib/pifinder/first-boot-target

      echo "Cleaning up migration closure..."
      nix-env --delete-generations +2 -p /nix/var/nix/profiles/system || true
      nix-collect-garbage || true

      echo "Rebooting into full PiFinder system..."
      systemctl reboot
    '';
  };

  # ---------------------------------------------------------------------------
  # Polkit rules for NetworkManager control
  # ---------------------------------------------------------------------------
  security.polkit.extraConfig = ''
    polkit.addRule(function(action, subject) {
      if (subject.user == "pifinder") {
        if (action.id.indexOf("org.freedesktop.NetworkManager") == 0) {
          return polkit.Result.YES;
        }
        if (action.id == "org.freedesktop.login1.reboot" ||
            action.id == "org.freedesktop.login1.reboot-multiple-sessions" ||
            action.id == "org.freedesktop.login1.power-off" ||
            action.id == "org.freedesktop.login1.power-off-multiple-sessions") {
          return polkit.Result.YES;
        }
      }
    });
  '';

  # ---------------------------------------------------------------------------
  # Sudoers — minimal for migration
  # ---------------------------------------------------------------------------
  security.sudo.extraRules = [{
    users = [ "pifinder" ];
    commands = [
      { command = "/run/current-system/sw/bin/shutdown -r now"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/shutdown now"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/hostname *"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/avahi-set-host-name *"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl restart pifinder-first-boot.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl restart pifinder*"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl status *"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/journalctl *"; options = [ "NOPASSWD" ]; }
    ];
  }];

  # ---------------------------------------------------------------------------
  # Early boot splash
  # ---------------------------------------------------------------------------
  systemd.services.boot-splash = {
    description = "Early boot splash screen";
    wantedBy = [ "sysinit.target" ];
    after = [ "systemd-modules-load.service" ];
    wants = [ "systemd-modules-load.service" ];
    unitConfig.DefaultDependencies = false;
    serviceConfig = {
      Type = "oneshot";
      ExecStart = pkgs.writeShellScript "boot-splash-wait" ''
        for i in $(seq 1 40); do
          [ -e /dev/spidev0.0 ] && exec ${boot-splash}/bin/boot-splash --static
          sleep 0.25
        done
        echo "SPI device never appeared" >&2
        exit 1
      '';
    };
  };

  # ---------------------------------------------------------------------------
  # SSH access
  # ---------------------------------------------------------------------------
  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = true;
      PermitRootLogin = "no";
    };
  };

  # ---------------------------------------------------------------------------
  # Avahi/mDNS for hostname discovery (pifinder.local)
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

  # Apply user-chosen hostname from PiFinder_data (survives NixOS rebuilds)
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

  # NetworkManager-wait-online adds ~10s to boot but is needed for
  # pifinder-first-boot to have internet. The first-boot script also has
  # its own connectivity retry loop as a fallback.
  systemd.services.NetworkManager-wait-online.serviceConfig.TimeoutStartSec = "30s";

  system.stateVersion = "24.11";
  }; # config
}
