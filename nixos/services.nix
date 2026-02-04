{ config, lib, pkgs, pifinderPythonEnv, ... }:
let
  cedar-detect = import ./pkgs/cedar-detect.nix { inherit pkgs; };
in {
  # ---------------------------------------------------------------------------
  # Cachix binary substituter — Pi downloads pre-built paths, never compiles
  # ---------------------------------------------------------------------------
  nix.settings = {
    substituters = [
      "https://cache.nixos.org"
      "https://pifinder.cachix.org"
    ];
    trusted-public-keys = [
      "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
      # TODO: Replace with actual key from Cachix dashboard
      "pifinder.cachix.org-1:REPLACE_WITH_ACTUAL_KEY"
    ];
    # No local builds — everything must come from a cache
    max-jobs = 0;
  };

  # ---------------------------------------------------------------------------
  # SD card optimizations
  # ---------------------------------------------------------------------------

  # Keep 2 generations max in bootloader
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

  fileSystems."/" = {
    options = [ "noatime" "nodiratime" ];
  };

  # ---------------------------------------------------------------------------
  # Tmpfiles — runtime directory for upgrade ref file
  # ---------------------------------------------------------------------------
  systemd.tmpfiles.rules = [
    "d /run/pifinder 0755 pifinder pifinder -"
  ];

  # ---------------------------------------------------------------------------
  # Sudoers — pifinder user can start upgrade and restart services
  # ---------------------------------------------------------------------------
  security.sudo.extraRules = [{
    users = [ "pifinder" ];
    commands = [
      { command = "/run/current-system/sw/bin/systemctl start pifinder-upgrade.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl reset-failed pifinder-upgrade.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl restart pifinder.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/nixos-rebuild *"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/shutdown *"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/chpasswd"; options = [ "NOPASSWD" ]; }
    ];
  }];

  # ---------------------------------------------------------------------------
  # Cedar Detect star detection gRPC server
  # ---------------------------------------------------------------------------
  systemd.services.cedar-detect = {
    description = "Cedar Detect Star Detection Server";
    after = [ "basic.target" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "idle";
      User = "pifinder";
      ExecStart = "${cedar-detect}/bin/cedar-detect-server --port 50551";
      Restart = "on-failure";
      RestartSec = 5;
    };
  };

  # ---------------------------------------------------------------------------
  # Main PiFinder application
  # ---------------------------------------------------------------------------
  systemd.services.pifinder = {
    description = "PiFinder";
    after = [ "basic.target" "cedar-detect.service" "gpsd.service" ];
    wants = [ "cedar-detect.service" "gpsd.service" ];
    wantedBy = [ "multi-user.target" ];
    environment = {
      PIFINDER_HOME = "/home/pifinder/PiFinder";
      PIFINDER_DATA = "/home/pifinder/PiFinder_data";
      GI_TYPELIB_PATH = lib.makeSearchPath "lib/girepository-1.0" [
        pkgs.networkmanager
        pkgs.glib
      ];
    };
    serviceConfig = {
      Type = "idle";
      User = "pifinder";
      WorkingDirectory = "/home/pifinder/PiFinder/python";
      ExecStart = "${pifinderPythonEnv}/bin/python -m PiFinder.main";
      AmbientCapabilities = "CAP_NET_BIND_SERVICE";
      Restart = "on-failure";
      RestartSec = 5;
    };
  };

  # ---------------------------------------------------------------------------
  # PiFinder Safe NixOS Upgrade (test-then-switch)
  # ---------------------------------------------------------------------------
  systemd.services.pifinder-upgrade = {
    description = "PiFinder Safe NixOS Upgrade (test-then-switch)";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "10min";
    };
    path = with pkgs; [ nixos-rebuild nix systemd coreutils ];
    script = ''
      set -euo pipefail
      REF=$(cat /run/pifinder/upgrade-ref 2>/dev/null || echo "release")
      FLAKE="github:mrosseel/PiFinder/''${REF}#pifinder"

      # Pre-flight: check disk space (need at least 500MB)
      AVAIL=$(df --output=avail /nix/store | tail -1)
      if [ "$AVAIL" -lt 524288 ]; then
        echo "ERROR: Less than 500MB free on /nix/store"
        exit 1
      fi

      echo "Phase 1: Download and activate (test mode — bootloader untouched)"
      nixos-rebuild test --flake "$FLAKE" --refresh

      echo "Phase 2: Verifying pifinder.service health"
      systemctl restart pifinder.service
      for i in $(seq 1 24); do
        if systemctl is-active --quiet pifinder.service; then
          echo "pifinder.service active after $((i * 5))s"

          echo "Phase 3: Persist to bootloader"
          nixos-rebuild switch --flake "$FLAKE"

          echo "Phase 4: Cleanup old generations"
          nix-env --delete-generations +2 -p /nix/var/nix/profiles/system || true
          nix-collect-garbage || true

          echo "Upgrade complete."
          exit 0
        fi
        sleep 5
      done

      echo "ERROR: pifinder.service not healthy. Rebooting to revert."
      systemctl reboot
    '';
  };

  # ---------------------------------------------------------------------------
  # PiFinder Boot Health Watchdog
  # ---------------------------------------------------------------------------
  systemd.services.pifinder-watchdog = {
    description = "PiFinder Boot Health Watchdog";
    after = [ "multi-user.target" "pifinder.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    path = with pkgs; [ systemd coreutils ];
    script = ''
      set -euo pipefail
      REBOOT_MARKER="/var/tmp/pifinder-watchdog-rebooted"

      if [ -f "$REBOOT_MARKER" ]; then
        echo "Watchdog already rebooted once. Not retrying."
        rm -f "$REBOOT_MARKER"
        exit 0
      fi

      echo "Watchdog: waiting up to 90s for pifinder.service..."
      for i in $(seq 1 18); do
        if systemctl is-active --quiet pifinder.service; then
          echo "pifinder.service healthy after $((i * 5))s"
          exit 0
        fi
        sleep 5
      done

      echo "ERROR: pifinder.service failed. Rolling back..."
      touch "$REBOOT_MARKER"
      PREV_GEN=$(ls -d /nix/var/nix/profiles/system-*-link 2>/dev/null | sort -t- -k2 -n | tail -2 | head -1)
      if [ -n "$PREV_GEN" ]; then
        "$PREV_GEN/bin/switch-to-configuration" switch || true
      fi
      systemctl reboot
    '';
  };

  # ---------------------------------------------------------------------------
  # GPSD for GPS receiver
  # ---------------------------------------------------------------------------
  services.gpsd = {
    enable = true;
    devices = [ "/dev/ttyAMA1" ];
    readonly = false;
  };

  # ---------------------------------------------------------------------------
  # Samba for file sharing (observation data, backups)
  # ---------------------------------------------------------------------------
  services.samba = {
    enable = true;
    settings = {
      global = {
        workgroup = "WORKGROUP";
        security = "user";
        "map to guest" = "never";
      };
      PiFinder_data = {
        path = "/home/pifinder/PiFinder_data";
        browseable = "yes";
        "read only" = "no";
        "valid users" = "pifinder";
      };
    };
  };
}
