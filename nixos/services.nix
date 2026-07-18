{ config, lib, pkgs, pifinderPythonEnv, ... }:
let
  cfg = config.pifinder;
  cedar-detect = import ./pkgs/cedar-detect.nix { inherit pkgs; };
  pifinder-src = import ./pkgs/pifinder-src.nix { inherit pkgs; };
  boot-splash = import ./pkgs/boot-splash.nix { inherit pkgs; };
  # Point the extlinux DEFAULT at a specific camera's boot entry. Device-tree
  # overlays load only at boot and the generic-extlinux builder always writes
  # DEFAULT=nixos-default (the base camera), so without this a switched camera
  # never actually boots its matching DTB. Boot-critical and best-effort: on any
  # doubt it leaves the existing (bootable) DEFAULT untouched.
  set-extlinux-default = pkgs.writeShellScriptBin "set-extlinux-default" ''
    set -euo pipefail
    CAM="''${1:?usage: set-extlinux-default <camera>}"
    CONF=/boot/extlinux/extlinux.conf

    [ -f "$CONF" ] || { echo "set-extlinux-default: $CONF missing" >&2; exit 0; }

    if [ "$CAM" = "${cfg.cameraType}" ]; then
      # The base camera is the builder's own default entry.
      TARGET=nixos-default
    else
      # Highest-numbered generation carrying this camera's specialisation entry.
      TARGET=$(grep -oE "^LABEL nixos-[0-9]+-$CAM" "$CONF" \
        | sed 's/^LABEL //' | sort -t- -k2,2n | tail -n1 || true)
    fi

    if [ -z "$TARGET" ] || ! grep -qx "LABEL $TARGET" "$CONF"; then
      echo "set-extlinux-default: no boot entry for '$CAM'; DEFAULT left unchanged" >&2
      exit 0
    fi

    TMP="$CONF.tmp.$$"
    sed "s/^DEFAULT .*/DEFAULT $TARGET/" "$CONF" > "$TMP"
    # Refuse to install anything that isn't exactly one DEFAULT pointing at a
    # real LABEL — a malformed extlinux.conf would brick the next boot.
    if [ "$(grep -c '^DEFAULT ' "$TMP")" = "1" ] && grep -qx "LABEL $TARGET" "$TMP"; then
      mv "$TMP" "$CONF"
      sync
      echo "set-extlinux-default: DEFAULT -> $TARGET" >&2
    else
      rm -f "$TMP"
      echo "set-extlinux-default: sanity check failed; DEFAULT left unchanged" >&2
      exit 0
    fi
  '';
  pifinder-switch-camera = pkgs.writeShellScriptBin "pifinder-switch-camera" ''
    set -euo pipefail
    CAM="''${1:?usage: pifinder-switch-camera <camera>}"
    PERSIST="/var/lib/pifinder/camera-type"
    mkdir -p /var/lib/pifinder

    # Accept only the base camera or a camera with a built specialisation.
    if [ "$CAM" != "${cfg.cameraType}" ] && [ ! -d "/run/current-system/specialisation/$CAM" ]; then
      echo "Unknown camera: $CAM" >&2
      exit 1
    fi

    # Regenerate the bootloader (installs every specialisation entry; 'boot'
    # mode touches no running services), make the chosen camera the boot
    # default, and persist the choice.
    /run/current-system/bin/switch-to-configuration boot
    ${set-extlinux-default}/bin/set-extlinux-default "$CAM"
    echo "$CAM" > "$PERSIST"

    # Device-tree overlays load only at boot, so apply the new camera by
    # rebooting into its entry.
    exec ${pkgs.systemd}/bin/systemctl reboot
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
    set-extlinux-default

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
  ] ++ lib.optionals cfg.devMode [
    # On-device development only (excluded from the production image). Not used
    # by the NixOS image updater, which is manifest/store-path based (ADR 0003).
    git             # clone/pull a checkout to run live
    rsync           # sync a checkout from a desktop without re-copying everything
  ];



  # ---------------------------------------------------------------------------
  # Binary substituters — Pi downloads pre-built paths, never compiles.
  # Two Attic caches on cache.pifinder.eu (NixOS ADR 0001):
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
      # Attic cache signing keys. pifinder is the original 8UU key: the S3
      # cutover briefly rotated it (Vkem), but nothing deployed trusted the new
      # key so the whole fleet was stranded — the cache and this config were
      # restored to 8UU. pifinder-release was minted fresh with the cutover (no
      # device trusted a release key before). Real keys — never swap one for a
      # placeholder; invalid base64 aborts every nix op and bricks upgrades.
      "pifinder:8UU/O3oLkaJHHUyqEcPGl+9F1m4MqDca39Ewl49jBmE="
      "pifinder-release:WG/Fw1cIX7YpwfWrbWTP5eCzn3bz6AaicW5qKxLKpoM="
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
      # Export PWM channels: 1 (GPIO 13, keypad backlight) and 0 (GPIO 12,
      # rev-4 buzzer — harmless no-op wiring on rev-3).
      for ch in 0 1; do
        if [ ! -d /sys/class/pwm/pwmchip0/pwm$ch ]; then
          echo $ch > /sys/class/pwm/pwmchip0/export || true
          sleep 0.5
        fi
      done
      # sysfs doesn't support chgrp, so make files world-writable
      chmod 0666 /sys/class/pwm/pwmchip0/export /sys/class/pwm/pwmchip0/unexport
      for ch in 0 1; do
        if [ -d /sys/class/pwm/pwmchip0/pwm$ch ]; then
          chmod 0666 /sys/class/pwm/pwmchip0/pwm$ch/{enable,period,duty_cycle,polarity}
        fi
      done
      # Red PWR LED — the app turns it off for night vision (sys_utils
      # set_power_led writes these directly, no sudo).
      if [ -d /sys/class/leds/PWR ]; then
        chmod 0666 /sys/class/leds/PWR/trigger /sys/class/leds/PWR/brightness
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
      # The app sends READY=1 once the UI is constructed and drawing
      # (utils.sd_notify in main.py). "active" therefore means "the screen is
      # live", which is what the boot watchdog's health check keys off — a
      # build that starts but never turns the screen on times out, restarts,
      # and fails its trial.
      Type = "notify";
      # Cold start on a Pi is ~30-60s (imports dominate); leave ample slack.
      TimeoutStartSec = 180;
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
  # PiFinder Network Policy
  # ---------------------------------------------------------------------------
  # Enforces connectivity priority wired > wifi client > AP via libnm
  # (PiFinder/net_policy.py). Event-driven on NetworkManager state changes;
  # brings the AP up only as an offline fallback and periodically drops an
  # idle AP so NM can rejoin a client network. The migration image, which has
  # no Python env, uses wifi-fallback-minimal.nix instead.
  systemd.services.pifinder-net-policy = {
    description = "PiFinder network policy (wired > wifi client > AP)";
    after = [ "NetworkManager.service" ];
    wants = [ "NetworkManager.service" ];
    wantedBy = [ "multi-user.target" ];
    path = [ pkgs.iw ];
    environment = {
      PIFINDER_DATA = "/home/pifinder/PiFinder_data";
      GI_TYPELIB_PATH = lib.makeSearchPath "lib/girepository-1.0" [
        pkgs.networkmanager
        pkgs.glib.out
        pkgs.gobject-introspection
      ];
    };
    serviceConfig = {
      WorkingDirectory = "/home/pifinder/PiFinder/python";
      ExecStart = "${pifinderPythonEnv}/bin/python -m PiFinder.net_policy";
      Restart = "always";
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
    path = with pkgs; [ nix systemd coreutils set-extlinux-default ];
  };

  # ---------------------------------------------------------------------------
  # PiFinder Boot Health Watchdog — self-arming trial/commit
  # ---------------------------------------------------------------------------
  # A generation is on probation until it has passed a health check once
  # (recorded in confirmed-generations). Any boot of an UNCONFIRMED generation
  # is a trial — whether or not the (possibly older, marker-unaware) system
  # that installed it armed the trial marker. Protection never depends on the
  # previous build's code.
  #   - confirmed generation  -> never roll back, so a transient failure in
  #     the field can't cause a surprise downgrade
  #   - trial gen healthy     -> confirm it
  #   - trial gen unhealthy   -> capture the journal to PiFinder_data (journald
  #     is volatile to spare the SD card; a failed boot is the one moment worth
  #     a write), leave a notice the app shows after reboot, show the failure
  #     splash, roll back (marker hint first, else newest other generation),
  #     reboot. With no rollback target at all, stay up for rescue instead of
  #     boot-looping.
  systemd.services.pifinder-watchdog = {
    description = "PiFinder Boot Health Watchdog";
    after = [ "multi-user.target" "pifinder.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    path = with pkgs; [ nix systemd coreutils jq gnugrep boot-splash ];
    script = ''
      set -euo pipefail
      MARKER=/var/lib/pifinder/trial-generation.json
      CONFIRMED=/var/lib/pifinder/confirmed-generations
      DATA=/home/pifinder/PiFinder_data
      CURRENT=$(readlink -f /run/current-system)

      is_confirmed() {
        [ -f "$CONFIRMED" ] && grep -qxF "$1" "$CONFIRMED"
      }

      if is_confirmed "$CURRENT"; then
        # Stale marker from an aborted/rolled-back upgrade attempt is harmless
        # here but must not survive to a later boot.
        rm -f "$MARKER"
        # Never ACT on a confirmed generation — but still REPORT (ADR 0005):
        # if the app can't start, the frozen splash gets replaced by an
        # advisory naming the recovery hold, so the escape hatch reveals
        # itself exactly when it is needed.
        echo "Generation already confirmed — report-only watch."
        for i in $(seq 1 24); do
          if systemctl is-active --quiet pifinder.service; then
            exit 0
          fi
          sleep 5
        done
        echo "Confirmed generation's app is not starting — showing recovery advisory (no action taken)."
        # The crash-looping app redraws its boot console between restarts, so
        # re-assert the advisory periodically (bounded — 30 min, then leave
        # the last draw standing) while bailing out if the app recovers.
        for i in $(seq 1 60); do
          if systemctl is-active --quiet pifinder.service; then
            exit 0
          fi
          boot-splash --message "PIFINDER" "FAILED TO START" "HOLD SQUARE" "AT POWER ON" "FOR RECOVERY" || true
          sleep 30
        done
        exit 0
      fi

      echo "Trial boot of unconfirmed generation $CURRENT: waiting up to 120s for pifinder.service..."
      for i in $(seq 1 24); do
        if systemctl is-active --quiet pifinder.service; then
          # Verify it stays running (not crash-looping)
          UPTIME=$(systemctl show pifinder.service --property=ExecMainStartTimestamp --value)
          START_EPOCH=$(date -d "$UPTIME" +%s 2>/dev/null || echo 0)
          NOW_EPOCH=$(date +%s)
          RUNNING_FOR=$((NOW_EPOCH - START_EPOCH))
          if [ "$RUNNING_FOR" -ge 15 ]; then
            echo "pifinder.service healthy (running ''${RUNNING_FOR}s) — confirming generation."
            mkdir -p "$(dirname "$CONFIRMED")"
            echo "$CURRENT" >> "$CONFIRMED"
            rm -f "$MARKER"
            exit 0
          fi
        fi
        sleep 5
      done

      # ----- unhealthy: pick a rollback target ------------------------------
      # Marker hint (exact pre-upgrade system, specialisation included) first;
      # otherwise walk the profile, newest first, skipping any generation that
      # boots into this same failed build (directly or via a specialisation)
      # and preferring confirmed generations.
      TARGET=""
      if [ -f "$MARKER" ]; then
        HINT=$(jq -r '.previous // empty' "$MARKER" 2>/dev/null || true)
        if [ -n "$HINT" ] && [ -e "$HINT" ] && [ "$HINT" != "$CURRENT" ]; then
          TARGET="$HINT"
        fi
      fi
      if [ -z "$TARGET" ]; then
        FALLBACK=""
        for GEN in $(ls -d /nix/var/nix/profiles/system-*-link 2>/dev/null | sort -t- -k2 -rn); do
          G=$(readlink -f "$GEN")
          [ "$G" = "$CURRENT" ] && continue
          SKIP=0
          for S in "$G"/specialisation/*/; do
            [ -e "$S" ] || continue
            [ "$(readlink -f "$S")" = "$CURRENT" ] && SKIP=1 && break
          done
          [ "$SKIP" = 1 ] && continue
          if is_confirmed "$G"; then
            TARGET="$G"
            break
          fi
          [ -z "$FALLBACK" ] && FALLBACK="$G"
        done
        [ -z "$TARGET" ] && TARGET="$FALLBACK"
      fi

      # ----- capture evidence ------------------------------------------------
      echo "ERROR: trial generation unhealthy. Capturing evidence..."
      TS=$(date +%Y%m%d-%H%M%S)
      mkdir -p "$DATA"
      journalctl -b > "$DATA/failed-boot-$TS.log" || true
      jq -n --arg failed "$CURRENT" --arg reverted_to "''${TARGET:-none}" --arg at "$TS" \
        '{failed: $failed, reverted_to: $reverted_to, at: $at}' \
        > "$DATA/upgrade_failed.json" || true
      chown pifinder:users "$DATA/failed-boot-$TS.log" "$DATA/upgrade_failed.json" 2>/dev/null || true

      # Stop the crash-looping app so the display is free for the failure
      # message (and so the reboot is clean).
      systemctl stop pifinder.service || true

      if [ -z "$TARGET" ]; then
        echo "FATAL: no rollback target exists — staying up for rescue (SSH) instead of boot-looping."
        boot-splash --message "UPDATE" "FAILED" "NO ROLLBACK" "USE SSH OR REFLASH" "HOLD SQ AT POWER ON" "FOR RECOVERY" || true
        exit 1
      fi

      boot-splash --message "UPDATE" "FAILED" "ROLLING BACK" "PLEASE WAIT" "HOLD SQ AT POWER ON" "FOR RECOVERY" || true

      echo "Rolling back to $TARGET and rebooting..."
      rm -f "$MARKER"
      # current-build.json was written for the (now failed) generation before
      # its reboot; left in place it makes the rolled-back system misreport
      # its identity (and the update UI mis-hide entries). Remove it — version
      # display falls back to the baked build metadata.
      rm -f /var/lib/pifinder/current-build.json
      nix-env -p /nix/var/nix/profiles/system --set "$TARGET"
      "$TARGET/bin/switch-to-configuration" boot || true
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

  # /etc/default/gpsd — same shape as upstream pi_config_files/gpsd.conf.
  # DEVICES opens the on-board UART GPS at startup via its stable udev name
  # (see hardware.nix — ttyAMA numbering shifts between kernels); USBAUTO lets
  # udev hotplug USB GPSes via gpsdctl. GPSD_SOCKET is intentionally omitted —
  # gpsd's default (/var/run/gpsd.sock) is already what we want.
  environment.etc."default/gpsd".text = ''
    DEVICES="/dev/gpsuart"
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

  # Add the on-board UART GPS to gpsd (uart3 overlay, published as
  # /dev/gpsuart by udev — platform UARTs are not auto-detected the way USB
  # GPSes are). Started by udev via SYSTEMD_WANTS when the device appears
  # (see hardware.nix), so a unit without an on-board GPS never starts it
  # and USB-only setups still work through USBAUTO hotplug alone.
  systemd.services.gpsd-add-uart = {
    description = "Add UART GPS to gpsd";
    after = [ "gpsd.socket" "dev-gpsuart.device" ];
    requires = [ "gpsd.socket" ];
    # BindsTo ensures this stops if the GPS UART disappears
    bindsTo = [ "dev-gpsuart.device" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.gpsd}/sbin/gpsdctl add /dev/gpsuart";
      ExecStop = "${pkgs.gpsd}/sbin/gpsdctl remove /dev/gpsuart";
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

  # Avahi/mDNS + the PiFinder custom-hostname service live in nixos/device.nix
  # (single owner — this block used to be duplicated here and there).

  # Don't block boot waiting for network — NM still works, just async
  systemd.services.NetworkManager-wait-online.enable = false;

  services.samba = {
    enable = true;
    openFirewall = true;
    settings = {
      global = {
        workgroup = "WORKGROUP";
        security = "user";
        # Anonymous access, as on the original Raspbian PiFinder: unauthenticated
        # clients are mapped to the pifinder user, which owns the share, so no SMB
        # password is ever needed. (Samba's passdb is separate from the Unix login,
        # so "solveit" never authenticated SMB anyway.)
        "map to guest" = "bad user";
        "guest account" = "pifinder";
      };
      PiFinder_data = {
        path = "/home/pifinder/PiFinder_data";
        browseable = "yes";
        "read only" = "no";
        "guest ok" = "yes";
      };
    };
  };

  # Advertise the Samba share over mDNS so it appears in file-manager "Network"
  # browse views (Finder, Nautilus). Samba itself never publishes an
  # _smb._tcp record; Avahi (configured in networking.nix) does the DNS-SD.
  # Lives here, tied to the samba block, so only the device build advertises it.
  services.avahi.extraServiceFiles.smb = ''
    <?xml version="1.0" standalone='no'?>
    <!DOCTYPE service-group SYSTEM "avahi-service.dtd">
    <service-group>
      <name replace-wildcards="yes">%h</name>
      <service>
        <type>_smb._tcp</type>
        <port>445</port>
      </service>
    </service-group>
  '';
  }; # config
}
