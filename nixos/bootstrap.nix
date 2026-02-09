# nixos/bootstrap.nix - Minimal NixOS for migration bootstrap
#
# This is a stripped-down NixOS configuration whose only purpose is to:
# 1. Boot on Pi 4
# 2. Connect to network (WiFi credentials migrated from RPi OS)
# 3. Run nixos-rebuild switch to become full PiFinder NixOS
# 4. Optionally resume user data restore if interrupted
#
# Size target: ~150MB compressed (vs ~900MB full PiFinder image)
{ config, lib, pkgs, ... }:

let
  # State directory for migration tracking
  stateDir = "/var/lib/pifinder-migration";

  # Migration progress script - writes state and optionally calls OLED binary
  # The OLED binary is placed at /bin/migration_progress by the initramfs
  progressScript = pkgs.writeShellScriptBin "migration-progress" ''
    PCT="$1"
    STATUS="$2"
    DETAIL="''${3:-}"

    # Write state file
    mkdir -p "${stateDir}"
    cat > "${stateDir}/state" <<EOF
    PHASE=3
    PERCENT=$PCT
    STATUS=$STATUS
    DETAIL=$DETAIL
    EOF

    # Try OLED binary if present (copied by initramfs)
    if [ -x /bin/migration_progress ]; then
      /bin/migration_progress "$PCT" "$STATUS" 2>/dev/null || true
    fi

    echo "[$PCT%] $STATUS $DETAIL"
  '';
in {
  # ---------------------------------------------------------------------------
  # Boot - minimal Pi 4 support
  # ---------------------------------------------------------------------------
  boot.loader.grub.enable = false;
  boot.loader.generic-extlinux-compatible.enable = true;
  boot.loader.generic-extlinux-compatible.configurationLimit = 2;

  boot.consoleLogLevel = 7;
  boot.kernelParams = [ "console=ttyS1,115200n8" ];

  # Minimal kernel modules
  boot.initrd.availableKernelModules = lib.mkForce [ "mmc_block" "usbhid" "usb_storage" ];
  boot.supportedFilesystems = lib.mkForce [ "vfat" "ext4" ];

  # ---------------------------------------------------------------------------
  # Filesystems
  # ---------------------------------------------------------------------------
  fileSystems."/" = {
    device = "/dev/disk/by-label/NIXOS_SD";
    fsType = "ext4";
    options = [ "noatime" "nodiratime" ];
  };

  fileSystems."/boot" = {
    device = "/dev/disk/by-label/FIRMWARE";
    fsType = "vfat";
  };

  # ---------------------------------------------------------------------------
  # Memory optimizations (same as full config)
  # ---------------------------------------------------------------------------
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

  # ---------------------------------------------------------------------------
  # Networking - wpa_supplicant + dhcpcd (minimal, no GTK deps)
  # NetworkManager pulls in 427MB of GTK via VPN deps
  # ---------------------------------------------------------------------------
  networking = {
    hostName = "pifinder-bootstrap";
    useDHCP = true;
    wireless = {
      enable = true;
      # WiFi creds will be in /etc/wpa_supplicant.conf (migrated from RPi OS)
      userControlled.enable = false;
    };
  };

  # ---------------------------------------------------------------------------
  # Nix with flakes + binary cache
  # ---------------------------------------------------------------------------
  nix.settings = {
    experimental-features = [ "nix-command" "flakes" ];
    substituters = [
      "https://cache.nixos.org"
      "https://pifinder.cachix.org"
    ];
    trusted-public-keys = [
      "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
      "pifinder.cachix.org-1:ALuxYs8tMU34zwSTWjenI2wpJA+AclmW6H5vyTgnTjc="
    ];
  };

  # ---------------------------------------------------------------------------
  # Minimal packages
  # ---------------------------------------------------------------------------
  # Minimal packages - nix has built-in git support for flakes
  environment.systemPackages = with pkgs; [
    progressScript
  ];

  # ---------------------------------------------------------------------------
  # Users - minimal, just for debugging/SSH
  # ---------------------------------------------------------------------------
  users.users.root.initialPassword = "solveit";
  users.users.pifinder = {
    isNormalUser = true;
    initialPassword = "solveit";
    extraGroups = [ "wheel" "systemd-journal" ];
  };

  # ---------------------------------------------------------------------------
  # SSH for debugging if bootstrap gets stuck
  # ---------------------------------------------------------------------------
  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = true;
      PermitRootLogin = "yes";
    };
  };

  # mDNS so we can find it at pifinder-bootstrap.local
  services.avahi = {
    enable = true;
    nssmdns4 = true;
    publish = {
      enable = true;
      addresses = true;
    };
  };

  # ---------------------------------------------------------------------------
  # Bootstrap Service - the main event
  # ---------------------------------------------------------------------------
  systemd.services.pifinder-bootstrap = {
    description = "PiFinder NixOS Bootstrap";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" "NetworkManager-wait-online.service" ];
    wants = [ "network-online.target" "NetworkManager-wait-online.service" ];

    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "on-failure";
      RestartSec = "30s";
      TimeoutStartSec = "30min";
    };

    # Minimal path - nixos-rebuild fetched at runtime to avoid pulling llvm into closure
    path = with pkgs; [ nix coreutils gnugrep gawk systemd inetutils ];

    script = ''
      set -euo pipefail

      STATE_FILE="${stateDir}/state"
      STAGING_META="${stateDir}/staging-meta"
      RESTORE_MARKER="${stateDir}/restore-complete"

      mkdir -p "${stateDir}"

      progress() {
        ${progressScript}/bin/migration-progress "$@"
      }

      # Already complete? Exit cleanly.
      if [ -f "$STATE_FILE" ] && grep -q "PERCENT=100" "$STATE_FILE"; then
        echo "Bootstrap already complete."
        exit 0
      fi

      progress 70 "NixOS booting"

      # -----------------------------------------------------------------------
      # Resume user data restore if interrupted
      # -----------------------------------------------------------------------
      if [ -f "$STAGING_META" ] && [ ! -f "$RESTORE_MARKER" ]; then
        progress 62 "Resuming data restore"

        source "$STAGING_META"
        # Variables from phase 2: STAGING_OFFSET_BLOCKS, BACKUP_SIZE, SD_DEV

        if [ -n "''${STAGING_OFFSET_BLOCKS:-}" ] && [ -n "''${BACKUP_SIZE:-}" ]; then
          BACKUP_BLOCKS=$(( (BACKUP_SIZE + 4095) / 4096 ))

          dd if="''${SD_DEV:-/dev/mmcblk0}" bs=4096 \
            skip="$STAGING_OFFSET_BLOCKS" count="$BACKUP_BLOCKS" 2>/dev/null | \
            gunzip | tar xf - -C /home/pifinder/ || {
              progress 62 "Restore failed" "will retry"
              exit 1
            }

          chown -R pifinder:users /home/pifinder/PiFinder_data 2>/dev/null || true
          touch "$RESTORE_MARKER"
          progress 67 "Data restored"
        fi
      fi

      # -----------------------------------------------------------------------
      # Wait for network
      # -----------------------------------------------------------------------
      progress 72 "Waiting for network"

      attempt=0
      max_attempts=120  # 10 minutes of trying

      while ! ping -c1 -W2 github.com &>/dev/null; do
        attempt=$((attempt + 1))

        if [ $attempt -ge $max_attempts ]; then
          # Reset counter, keep trying forever
          progress 72 "No network" "retry $attempt - check WiFi"
          attempt=0
          sleep 30
          continue
        fi

        # Show connection status
        conn_state=$(ip route get 8.8.8.8 2>/dev/null | head -1 || echo "no route")
        progress 72 "Connecting..." "$conn_state"
        sleep 5
      done

      progress 75 "Network connected"

      # -----------------------------------------------------------------------
      # nixos-rebuild switch
      # -----------------------------------------------------------------------
      progress 76 "Starting switch"

      FLAKE="github:brickbots/PiFinder/release#pifinder"

      # Fetch nixos-rebuild at runtime to avoid bloating bootstrap closure
      # This adds ~30s but saves ~500MB in the tarball
      progress 77 "Fetching tools"

      # Parse nix build output for progress
      if nix shell nixpkgs#nixos-rebuild -c nixos-rebuild switch --flake "$FLAKE" --refresh 2>&1 | \
         while IFS= read -r line; do
           echo "$line"  # Pass through for logging

           # Parse copying progress
           if echo "$line" | grep -qE 'copying path.*\([0-9]+/[0-9]+\)'; then
             nums=$(echo "$line" | grep -oE '\([0-9]+/[0-9]+\)' | tr -d '()')
             done=$(echo "$nums" | cut -d/ -f1)
             total=$(echo "$nums" | cut -d/ -f2)
             if [ "$total" -gt 0 ]; then
               pct=$((done * 100 / total))
               # Map 0-100% to 78-95%
               mapped=$((78 + pct * 17 / 100))
               progress "$mapped" "Downloading" "$done/$total paths"
             fi
           elif echo "$line" | grep -qi 'activating'; then
             progress 95 "Activating system"
           fi
         done; then

        progress 98 "Finalizing"

        # Cleanup migration artifacts
        rm -f /boot/nixos_migration
        rm -f /boot/initramfs-migration.gz

        # Expand root partition if not already done
        # (in case phase 2 was interrupted before expand)
        if command -v sfdisk >/dev/null 2>&1; then
          echo ", +" | sfdisk -N 2 /dev/mmcblk0 --no-reread 2>/dev/null || true
          partprobe /dev/mmcblk0 2>/dev/null || true
          resize2fs /dev/mmcblk0p2 2>/dev/null || true
        fi

        progress 100 "Complete!" "Rebooting..."
        sleep 3

        systemctl reboot
      else
        progress 76 "Switch failed" "retrying in 30s..."
        exit 1  # systemd will restart after 30s
      fi
    '';
  };

  # ---------------------------------------------------------------------------
  # System
  # ---------------------------------------------------------------------------
  system.stateVersion = "24.11";

  # Strip unnecessary stuff
  documentation.enable = false;
  documentation.man.enable = false;
  documentation.nixos.enable = false;
  fonts.fontconfig.enable = false;
  xdg.portal.enable = false;
  services.xserver.enable = false;

  # Remove default packages that bloat the image
  environment.defaultPackages = lib.mkForce [];
  programs.nano.enable = false;
  programs.vim.defaultEditor = false;
  programs.command-not-found.enable = false;  # pulls perl
  programs.less.lessopen = null;  # lesspipe pulls perl (112MB)

  # Disable unnecessary services
  services.udisks2.enable = false;
  security.polkit.enable = lib.mkForce false;
  services.speechd.enable = lib.mkForce false;

  # Disable xdg stuff that pulls in perl via xdg-utils
  xdg.mime.enable = false;
  xdg.icons.enable = false;
  xdg.sounds.enable = false;
  xdg.autostart.enable = false;

  # Disable fuse/fusermount (86MB)
  programs.fuse.userAllowOther = false;
  boot.initrd.supportedFilesystems = lib.mkForce [];

  # Minimal nix - no gc, no daemon overhead
  nix.gc.automatic = false;
}
