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
  # First boot: download full PiFinder system from cachix and switch
  # ---------------------------------------------------------------------------
  systemd.services.pifinder-first-boot = {
    description = "Download full PiFinder NixOS system from cachix";
    after = [ "network-online.target" "nix-path-registration.service" "nix-daemon.service" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    unitConfig.ConditionPathExists = "/var/lib/pifinder/first-boot-target";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "30min";
    };
    path = with pkgs; [ nix coreutils systemd ];
    script = ''
      set -euo pipefail

      STORE_PATH=$(cat /var/lib/pifinder/first-boot-target)
      if [ -z "$STORE_PATH" ] || [[ "$STORE_PATH" != /nix/store/* ]]; then
        echo "ERROR: Invalid store path: $STORE_PATH"
        exit 1
      fi

      echo "Downloading full PiFinder system: $STORE_PATH"
      nix build "$STORE_PATH" --max-jobs 0

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
      }
    });
  '';

  # ---------------------------------------------------------------------------
  # Sudoers — minimal for migration
  # ---------------------------------------------------------------------------
  security.sudo.extraRules = [{
    users = [ "pifinder" ];
    commands = [
      { command = "/run/current-system/sw/bin/shutdown *"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/hostname *"; options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/dmesg"; options = [ "NOPASSWD" ]; }
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

  systemd.services.NetworkManager-wait-online.enable = false;

  system.stateVersion = "24.11";
  }; # config
}
