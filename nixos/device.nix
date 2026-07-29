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
    # nano over vim: 40MB smaller on a size-critical image (2GB boards must
    # hold the whole tarball in RAM during migration)
    nano
    htop
    e2fsprogs
    dosfstools
    parted
    file
    curl
  ];


  # ---------------------------------------------------------------------------
  # Binary substituters — Pi downloads pre-built paths, never compiles.
  # Two Attic caches on cache.pifinder.eu (NixOS ADR 0001): pifinder-release
  # (retained release closures) and pifinder (dev/nightly). The first-boot
  # download below resolves its target from the update manifest's best available
  # channel (NixOS ADR 0003).
  # ---------------------------------------------------------------------------
  nix.settings = {
    experimental-features = [ "nix-command" "flakes" ];
    substituters = [
      "https://cache.pifinder.eu/pifinder-release"
      "https://cache.pifinder.eu/pifinder"
      "https://cache.nixos.org"
    ];
    trusted-public-keys = [
      # Attic cache signing keys (same values as nixos/services.nix); pifinder
      # restored to the original 8UU after the cutover rotation stranded the
      # fleet. Real keys — never ship a placeholder; invalid base64 aborts nix.
      "pifinder:8UU/O3oLkaJHHUyqEcPGl+9F1m4MqDca39Ewl49jBmE="
      "pifinder-release:WG/Fw1cIX7YpwfWrbWTP5eCzn3bz6AaicW5qKxLKpoM="
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
    # No existence condition: the manifest is the primary source (ADR 0003) and
    # needs no local file. The baked first-boot-target, when present, is only
    # the offline fallback — the old ConditionPathExists on it silently skipped
    # the whole service when the tarball pipeline stopped baking the file.
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

      # Resolve the full system from the update manifest — the same file the
      # on-device updater reads (NixOS ADR 0003). Migration rides the newest entry
      # in the best available channel: stable, then beta, then the unstable trunk.
      # Stable holds only releases, whose closures live in the retained
      # pifinder-release cache, so a resolved stable path can't be GC'd out from
      # under a published tarball. Falls back to the baked-in target if the
      # manifest can't be fetched.
      MANIFEST_URL="https://raw.githubusercontent.com/brickbots/PiFinder/nixos-manifest/update-manifest.json"
      STORE_PATH=""
      if MANIFEST_JSON=$(curl -sf --max-time 15 "$MANIFEST_URL" 2>/dev/null); then
        # jq comma-stream encodes the priority order; first available, valid path
        # wins. TEMPORARY: the unstable trunk is pinned to source_ref "nixos"
        # because the NixOS line still lives on the nixos branch, not main. Drop
        # the source_ref guard once nixos becomes the mainline trunk (ADR 0003).
        STORE_PATH=$(printf '%s\n' "$MANIFEST_JSON" | jq -r '
          [ ( .channels.stable[]?,
              .channels.beta[]?,
              (.channels.unstable[]? | select(.kind == "trunk" and .source_ref == "nixos")) )
            | select(.available == true and ((.store_path // "") | startswith("/nix/store/")))
            | .store_path ] | .[0] // empty' 2>/dev/null)
        [ -n "$STORE_PATH" ] && echo "Resolved full system from manifest: $STORE_PATH"
      fi
      if [ -z "$STORE_PATH" ] || [[ "$STORE_PATH" != /nix/store/* ]]; then
        echo "Manifest unavailable or empty, falling back to baked-in target"
        [ -f /var/lib/pifinder/first-boot-target ] && \
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
      [ "$TOTAL_PATHS" -gt 0 ] 2>/dev/null || TOTAL_PATHS=0
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

      # Record the device identity: the update UI hides the running build by
      # store path (current-build.json), and every later upgrade rewrites this
      # file. Label/version/channel come from the manifest entry we resolved;
      # a fallback-target install records just the store path.
      IDENTITY=$(printf '%s\n' "''${MANIFEST_JSON:-}" | jq -c --arg sp "$STORE_PATH" '
        [ .channels | to_entries[] | .key as $ch | .value[]?
          | select(.store_path == $sp)
          | {channel: $ch, label: .label, version: .version, store_path: .store_path} ]
        | .[0] // empty' 2>/dev/null)
      [ -n "$IDENTITY" ] || IDENTITY=$(jq -nc --arg sp "$STORE_PATH" '{store_path: $sp}')
      printf '%s\n' "$IDENTITY" > /var/lib/pifinder/current-build.json

      echo "Configuring bootloader..."
      "$STORE_PATH/bin/switch-to-configuration" boot

      echo "Removing first-boot trigger..."
      rm -f /var/lib/pifinder/first-boot-target

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

  # NetworkManager-wait-online adds ~10s to boot but is needed for
  # pifinder-first-boot to have internet. The first-boot script also has
  # its own connectivity retry loop as a fallback.
  systemd.services.NetworkManager-wait-online.serviceConfig.TimeoutStartSec = "30s";

  system.stateVersion = "24.11";
  }; # config
}
