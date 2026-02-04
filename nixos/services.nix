{ config, lib, pkgs, pifinderPythonEnv, ... }:
let
  cfg = config.pifinder;
  cedar-detect = import ./pkgs/cedar-detect.nix { inherit pkgs; };
  pifinder-src = import ./pkgs/pifinder-src.nix { inherit pkgs; };
in {
  options.pifinder = {
    devMode = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable development mode (NFS netboot support, etc.)";
    };
  };

  # ---------------------------------------------------------------------------
  # Cachix binary substituter — Pi downloads pre-built paths, never compiles
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

  fileSystems."/" = lib.mkDefault {
    device = "/dev/disk/by-label/NIXOS_SD";
    fsType = "ext4";
    options = [ "noatime" "nodiratime" ];
  };

  # ---------------------------------------------------------------------------
  # Tmpfiles — runtime directory for upgrade ref file
  # ---------------------------------------------------------------------------
  systemd.tmpfiles.rules = [
    "d /run/pifinder 0755 pifinder pifinder -"
  ];

  # ---------------------------------------------------------------------------
  # PiFinder source + data directory setup
  # ---------------------------------------------------------------------------
  system.activationScripts.pifinder-home = lib.stringAfter [ "users" ] ''
    # Symlink immutable source tree from Nix store
    # Database is opened read-only, so no need for writable copy
    PFHOME=/home/pifinder/PiFinder

    # Remove existing directory (not symlink) to allow symlink creation
    if [ -e "$PFHOME" ] && [ ! -L "$PFHOME" ]; then
      rm -rf "$PFHOME"
    fi

    # Create symlink to immutable Nix store path
    ln -sfT ${pifinder-src} "$PFHOME"

    # Create writable data directory
    mkdir -p /home/pifinder/PiFinder_data
    chown pifinder:users /home/pifinder/PiFinder_data
  '';

  # ---------------------------------------------------------------------------
  # Sudoers — pifinder user can start upgrade and restart services
  # ---------------------------------------------------------------------------
  # Polkit rules for pifinder user (D-Bus hostname changes, NetworkManager)
  security.polkit.extraConfig = ''
    polkit.addRule(function(action, subject) {
      if (subject.user == "pifinder") {
        // Allow hostname changes via systemd-hostnamed
        if (action.id == "org.freedesktop.hostname1.set-static-hostname" ||
            action.id == "org.freedesktop.hostname1.set-hostname") {
          return polkit.Result.YES;
        }
        // Allow NetworkManager control
        if (action.id.indexOf("org.freedesktop.NetworkManager") == 0) {
          return polkit.Result.YES;
        }
      }
    });
  '';

  security.sudo.extraRules = [{
    users = [ "pifinder" ];
    commands = [
      { command = "/run/current-system/sw/bin/systemctl start pifinder-upgrade.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl reset-failed pifinder-upgrade.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl restart pifinder.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl restart avahi-daemon.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/nixos-rebuild *"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/shutdown *"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/chpasswd"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/dmesg"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/hostnamectl *"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/tee /boot/camera.txt"; options = [ "NOPASSWD" ]; }
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
    after = [ "basic.target" "cedar-detect.service" "gpsd.socket" ];
    wants = [ "cedar-detect.service" "gpsd.socket" ];
    wantedBy = [ "multi-user.target" ];
    path = [ pkgs.gpsd ];  # For gpsctl
    environment = {
      PIFINDER_HOME = "/home/pifinder/PiFinder";
      PIFINDER_DATA = "/home/pifinder/PiFinder_data";
      GI_TYPELIB_PATH = lib.makeSearchPath "lib/girepository-1.0" [
        pkgs.networkmanager
        pkgs.glib.out  # Use .out to get the main package with typelibs, not glib-bin
        pkgs.gobject-introspection
      ];
      # libcamera Python bindings for picamera2
      PYTHONPATH = "${pkgs.libcamera}/lib/python3.12/site-packages";
    };
    serviceConfig = {
      Type = "idle";
      User = "pifinder";
      Group = "users";
      WorkingDirectory = "/home/pifinder/PiFinder/python";
      ExecStart = "${pifinderPythonEnv}/bin/python -m PiFinder.main";
      # Allow binding to privileged ports (80 for web UI)
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
      # Single universal build - camera is selected at runtime via /boot/camera.txt
      FLAKE="github:brickbots/PiFinder/''${REF}#pifinder"

      # Pre-flight: check disk space (need at least 500MB)
      AVAIL=$(df --output=avail /nix/store | tail -1)
      if [ "$AVAIL" -lt 524288 ]; then
        echo "ERROR: Less than 500MB free on /nix/store"
        exit 1
      fi

      echo "Upgrading to $FLAKE"

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
  # GPSD for GPS receiver - full USB hotplug support
  # ---------------------------------------------------------------------------
  # Don't use services.gpsd module - it doesn't support hotplug.
  # Instead, use gpsd's own systemd units with socket activation.

  # Install gpsd's udev rules (25-gpsd.rules) for USB GPS auto-detection
  # Includes u-blox 5/6/7/8/9 and many other GPS receivers
  services.udev.packages = [ pkgs.gpsd ];

  # Install gpsd's systemd units (gpsd.service, gpsd.socket, gpsdctl@.service)
  systemd.packages = [ pkgs.gpsd ];

  # Enable socket activation - gpsd starts when something connects to port 2947
  systemd.sockets.gpsd = {
    wantedBy = [ "sockets.target" ];
  };

  # Configure USBAUTO for gpsdctl (triggered by udev when USB GPS plugs in)
  environment.etc."default/gpsd".text = ''
    USBAUTO="true"
    GPSD_SOCKET="/var/run/gpsd.sock"
  '';

  # Ensure gpsd user/group exist (normally created by services.gpsd module)
  users.users.gpsd = {
    isSystemUser = true;
    group = "gpsd";
    description = "GPSD daemon user";
  };
  users.groups.gpsd = {};

  # Add UART GPS on boot (ttyAMA3 from uart3 overlay, not auto-detected by udev)
  # This runs after gpsd.socket is ready, adding the UART device to gpsd
  systemd.services.gpsd-add-uart = {
    description = "Add UART GPS to gpsd";
    after = [ "gpsd.socket" "dev-ttyAMA3.device" ];
    requires = [ "gpsd.socket" ];
    wantedBy = [ "multi-user.target" ];
    # BindsTo ensures this stops if ttyAMA3 disappears (though it shouldn't)
    bindsTo = [ "dev-ttyAMA3.device" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.gpsd}/sbin/gpsdctl add /dev/ttyAMA3";
      ExecStop = "${pkgs.gpsd}/sbin/gpsdctl remove /dev/ttyAMA3";
    };
  };

  # ---------------------------------------------------------------------------
  # Samba for file sharing (observation data, backups)
  # ---------------------------------------------------------------------------
  system.stateVersion = "24.11";

  # ---------------------------------------------------------------------------
  # SSH access
  # ---------------------------------------------------------------------------
  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = true;
      PermitRootLogin = "yes";
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
