{ config, lib, pkgs, pifinderPythonEnv, ... }:
let
  cfg = config.pifinder;
  cedar-detect = import ./pkgs/cedar-detect.nix { inherit pkgs; };
  pifinder-src = import ./pkgs/pifinder-src.nix { inherit pkgs; };
  boot-splash = import ./pkgs/boot-splash.nix { inherit pkgs; };
  pifinder-switch-camera = pkgs.writeShellScriptBin "pifinder-switch-camera" ''
    CAM="$1"
    PERSIST="/var/lib/pifinder/camera-type"
    mkdir -p /var/lib/pifinder

    SPEC="/run/current-system/specialisation/$CAM"
    if [ "$CAM" = "${cfg.cameraType}" ]; then
      /run/current-system/bin/switch-to-configuration boot
    elif [ -d "$SPEC" ]; then
      "$SPEC/bin/switch-to-configuration" boot
    else
      echo "Unknown camera: $CAM" >&2; exit 1
    fi
    echo "$CAM" > "$PERSIST"
  '';
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
  # Camera switch wrapper (used by pifinder UI via sudo)
  # ---------------------------------------------------------------------------
  environment.systemPackages = with pkgs; [
    pifinder-switch-camera

    # Diagnostic tools for SSH troubleshooting
    htop
    vim
    tcpdump
    iftop
    lsof
    strace
    file
    dnsutils        # dig, nslookup
    curl
    usbutils        # lsusb
    pciutils        # lspci
    i2c-tools       # i2cdetect (sensor debugging)
    iotop
  ];



  # ---------------------------------------------------------------------------
  # Binary substituters — Pi downloads pre-built paths, never compiles.
  # Two Attic caches on cache.pifinder.eu (ADR 0004):
  #   pifinder-release — tagged release closures, never garbage-collected, so a
  #                      device upgrading long after a release still resolves it.
  #   pifinder         — dev/nightly builds, short retention.
  # cache.nixos.org serves everything not built locally.
  # ---------------------------------------------------------------------------
  nix.settings = {
    experimental-features = [ "nix-command" "flakes" ];
    substituters = [
      "https://cache.pifinder.eu/pifinder-release"
      "https://cache.pifinder.eu/pifinder"
      "https://cache.nixos.org"
    ];
    trusted-public-keys = [
      # NOTE: pifinder-release's key goes here once that cache is provisioned
      # (`attic cache create pifinder-release`). Do NOT add a placeholder — an
      # invalid base64 key makes nix abort every operation ("invalid character
      # in Base64 string"), bricking upgrades. Until then the pifinder-release
      # substituter simply serves nothing this device trusts, which is fine.
      "pifinder:8UU/O3oLkaJHHUyqEcPGl+9F1m4MqDca39Ewl49jBmE="
      "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
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
  # Disable store optimization on NFS (hard links cause issues)
  nix.settings.auto-optimise-store = !cfg.devMode;

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
    "d /run/pifinder 0755 pifinder users -"
  ];

  # ---------------------------------------------------------------------------
  # PWM permissions setup for keypad backlight
  # ---------------------------------------------------------------------------
  systemd.services.pwm-permissions = {
    description = "Set PWM sysfs permissions for pifinder";
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      # Export PWM channel 1 (GPIO 13) if not already exported
      if [ ! -d /sys/class/pwm/pwmchip0/pwm1 ]; then
        echo 1 > /sys/class/pwm/pwmchip0/export || true
        sleep 0.5
      fi
      # sysfs doesn't support chgrp, so make files world-writable
      chmod 0666 /sys/class/pwm/pwmchip0/export /sys/class/pwm/pwmchip0/unexport
      if [ -d /sys/class/pwm/pwmchip0/pwm1 ]; then
        chmod 0666 /sys/class/pwm/pwmchip0/pwm1/{enable,period,duty_cycle,polarity}
      fi
    '';
  };

  # ---------------------------------------------------------------------------
  # Nix DB registration (first boot after migration)
  # ---------------------------------------------------------------------------
  # The migration tarball includes /nix-path-registration with store path data.
  # Load it into the Nix DB so nix-store and nixos-rebuild work correctly.
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
  # Repair /nix/store ownership before NetworkManager starts
  # ---------------------------------------------------------------------------
  # NetworkManager (like other security-sensitive plugin loaders) silently
  # refuses to load any plugin file not owned by root. Tarball-based migration
  # and single-user nix imports can leave /nix/store paths owned by a non-root
  # uid; NM then drops its wifi device plugin entirely — wlan0 shows as
  # "unmanaged", WIFI-HW as "missing", and no wifi client connection ever comes
  # up. Normalise ownership back to root before NM reads its plugins. Idempotent
  # and cheap on a clean store (early-exits without touching the ro mount).
  systemd.services.fix-nix-store-ownership = {
    description = "Normalise /nix/store ownership to root (NM rejects non-root plugins)";
    after = [ "local-fs.target" ];
    before = [ "NetworkManager.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    path = with pkgs; [ util-linux findutils coreutils ];
    script = ''
      set -u
      if [ -z "$(find /nix/store -mindepth 1 -maxdepth 1 ! -uid 0 -print -quit)" ] \
         && [ "$(stat -c %u /nix/var/nix/db)" = 0 ]; then
        exit 0
      fi
      echo "normalising non-root /nix/store ownership"
      # /nix/store is a read-only bind mount of the same device as /. The
      # remount MUST carry "bind" so it flips only this mount's per-mount
      # ro flag; a plain "remount,ro" would flip the shared superblock and
      # take / (and /nix/var) read-only with it.
      remounted=0
      if findmnt -no OPTIONS /nix/store | grep -qw ro; then
        if mount -o remount,bind,rw /nix/store; then
          remounted=1
        else
          echo "WARNING: could not remount /nix/store rw; skipping repair"
          exit 0
        fi
      fi
      find /nix/store -mindepth 1 -maxdepth 1 ! -uid 0 -exec chown -R 0:0 {} + || true
      chown 0:0 /nix/var/nix/db || true
      if [ "$remounted" = 1 ]; then
        mount -o remount,bind,ro /nix/store || true
      fi
      echo "store ownership normalised"
    '';
  };

  # ---------------------------------------------------------------------------
  # PiFinder source + data directory setup
  # ---------------------------------------------------------------------------
  system.activationScripts.pifinder-home = lib.stringAfter [ "users" ] ''
    # Create writable data directory
    mkdir -p /home/pifinder/PiFinder_data
    chown pifinder:users /home/pifinder/PiFinder_data

    # Symlink immutable source tree from Nix store
    # Database is opened read-only, so no need for writable copy
    PFHOME=/home/pifinder/PiFinder

    # Remove existing directory (not symlink) to allow symlink creation
    if [ -e "$PFHOME" ] && [ ! -L "$PFHOME" ]; then
      rm -rf "$PFHOME"
    fi

    # Create symlink to immutable Nix store path
    ln -sfT ${pifinder-src} "$PFHOME"
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
        // Allow reboot/shutdown via D-Bus (logind)
        if (action.id == "org.freedesktop.login1.reboot" ||
            action.id == "org.freedesktop.login1.reboot-multiple-sessions" ||
            action.id == "org.freedesktop.login1.power-off" ||
            action.id == "org.freedesktop.login1.power-off-multiple-sessions") {
          return polkit.Result.YES;
        }
      }
    });
  '';

  security.sudo.extraRules = [{
    users = [ "pifinder" ];
    commands = [
      { command = "/run/current-system/sw/bin/systemctl start --no-block pifinder-upgrade.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl start pifinder-upgrade.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl reset-failed pifinder-upgrade.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl restart pifinder.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl stop pifinder.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl start pifinder.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl restart avahi-daemon.service"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/avahi-set-host-name *"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/shutdown -r now"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/shutdown now"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/chpasswd"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/hostname *"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/pifinder-switch-camera imx296"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/pifinder-switch-camera imx462"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/pifinder-switch-camera imx477"; options = [ "NOPASSWD" ]; }
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
  # Early boot splash — show static welcome image, pifinder overwrites when ready
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
  # Main PiFinder application
  # ---------------------------------------------------------------------------
  systemd.services.pifinder = {
    description = "PiFinder";
    after = [ "basic.target" "cedar-detect.service" "gpsd.socket" ];
    wants = [ "cedar-detect.service" "gpsd.socket" ];
    wantedBy = [ "multi-user.target" ];
    path = let
      # Runtime paths not in the nix store — symlinks resolve at boot, not build time
      wrapperBins = pkgs.runCommand "wrapper-bins" {} ''
        mkdir -p $out
        ln -s /run/wrappers/bin $out/bin
      '';
      systemBins = pkgs.runCommand "system-bins" {} ''
        mkdir -p $out
        ln -s /run/current-system/sw/bin $out/bin
      '';
    in [ wrapperBins systemBins pkgs.gpsd ];
    environment = {
      PIFINDER_HOME = "/home/pifinder/PiFinder";
      PIFINDER_DATA = "/home/pifinder/PiFinder_data";
      GI_TYPELIB_PATH = lib.makeSearchPath "lib/girepository-1.0" [
        pkgs.networkmanager
        pkgs.glib.out  # Use .out to get the main package with typelibs, not glib-bin
        pkgs.gobject-introspection
      ];
      # libcamera Python bindings for picamera2
      PYTHONPATH = "${pkgs.libcamera}/lib/python3.13/site-packages";
      # libcamera IPA modules path
      LIBCAMERA_IPA_MODULE_PATH = "${pkgs.libcamera}/lib/libcamera";
    };
    serviceConfig = {
      Type = "simple";
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
  # PiFinder NixOS Upgrade
  # ---------------------------------------------------------------------------
  # Downloads from binary caches, sets profile, updates bootloader, reboots.
  # No live switch-to-configuration — avoids killing running services.
  # The pifinder-watchdog handles rollback if the new generation fails to boot.
  systemd.services.pifinder-upgrade = {
    description = "PiFinder NixOS Upgrade";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      WorkingDirectory = "/home/pifinder/PiFinder/python";
      ExecStart = "${pifinderPythonEnv}/bin/python -m PiFinder.nixos_upgrade --default-camera ${cfg.cameraType}";
    };
    path = with pkgs; [ nix systemd coreutils ];
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
    path = with pkgs; [ nix systemd coreutils ];
    script = ''
      set -euo pipefail
      REBOOT_MARKER="/var/tmp/pifinder-watchdog-rebooted"

      if [ -f "$REBOOT_MARKER" ]; then
        echo "Watchdog already rebooted once. Not retrying."
        rm -f "$REBOOT_MARKER"
        exit 0
      fi

      echo "Watchdog: waiting up to 120s for pifinder.service..."
      for i in $(seq 1 24); do
        if systemctl is-active --quiet pifinder.service; then
          # Verify it stays running (not crash-looping)
          UPTIME=$(systemctl show pifinder.service --property=ExecMainStartTimestamp --value)
          START_EPOCH=$(date -d "$UPTIME" +%s 2>/dev/null || echo 0)
          NOW_EPOCH=$(date +%s)
          RUNNING_FOR=$((NOW_EPOCH - START_EPOCH))
          if [ "$RUNNING_FOR" -ge 15 ]; then
            echo "pifinder.service healthy (running ''${RUNNING_FOR}s)"
            exit 0
          fi
        fi
        sleep 5
      done

      echo "ERROR: pifinder.service failed. Rolling back..."
      touch "$REBOOT_MARKER"
      PREV_GEN=$(ls -d /nix/var/nix/profiles/system-*-link 2>/dev/null | sort -t- -k2 -n | tail -2 | head -1)
      if [ -n "$PREV_GEN" ]; then
        # Reset profile so the rolled-back generation becomes the current one
        nix-env -p /nix/var/nix/profiles/system --set "$(readlink -f "$PREV_GEN")"
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

  # /etc/default/gpsd — kept identical to upstream pi_config_files/gpsd.conf so
  # the Debian and NixOS images present the same operator-visible config.
  # DEVICES opens the on-board UART GPS at startup; USBAUTO lets udev hotplug
  # USB GPSes via gpsdctl. GPSD_SOCKET is intentionally omitted — gpsd's
  # default (/var/run/gpsd.sock) is already what we want.
  environment.etc."default/gpsd".text = ''
    DEVICES="/dev/ttyAMA1"
    GPSD_OPTIONS=""
    USBAUTO="true"
  '';

  # Ensure gpsd user/group exist (normally created by services.gpsd module)
  users.users.gpsd = {
    isSystemUser = true;
    group = "gpsd";
    description = "GPSD daemon user";
  };
  users.groups.gpsd = {};

  # Add UART GPS on boot (ttyAMA1 from uart3 overlay, not auto-detected by udev)
  # This runs after gpsd.socket is ready, adding the UART device to gpsd
  systemd.services.gpsd-add-uart = {
    description = "Add UART GPS to gpsd";
    after = [ "gpsd.socket" "dev-ttyAMA1.device" ];
    requires = [ "gpsd.socket" ];
    wantedBy = [ "multi-user.target" ];
    # BindsTo ensures this stops if ttyAMA1 disappears (though it shouldn't)
    bindsTo = [ "dev-ttyAMA1.device" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.gpsd}/sbin/gpsdctl add /dev/ttyAMA1";
      ExecStop = "${pkgs.gpsd}/sbin/gpsdctl remove /dev/ttyAMA1";
    };
  };

  # ---------------------------------------------------------------------------
  # PAM service for PiFinder web UI password verification
  # ---------------------------------------------------------------------------
  security.pam.services.pifinder = {
    # Auth-only: no account/session management (avoids setuid and pam_lastlog2 errors)
    allowNullPassword = false;
    unixAuth = true;
    setLoginUid = false;
    updateWtmp = false;
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

  # Clean stale PID file so avahi restarts cleanly during switch-to-configuration
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

  # Don't block boot waiting for network — NM still works, just async
  systemd.services.NetworkManager-wait-online.enable = false;

  services.samba = {
    enable = true;
    openFirewall = true;
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
  }; # config
}
