{ pkgs, ... }:
# Pi OS migration (ADR 0039): what NixOS does with what the migration left
# on the card. Only devices that came from Pi OS need this; a device flashed
# with a NixOS image finds nothing to do, and every service here checks for
# its input first. The migration system (device.nix) and the full system
# both import this module: the migration system boots first on the
# converted card, and the full system repairs devices migrated by an older
# migration.
{
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
  # Repair top-level directory ownership
  # ---------------------------------------------------------------------------
  # A tarball migration can leave /, /var, /nix and other top-level
  # directories owned by the pifinder user. systemd-tmpfiles then rejects the
  # "unsafe path transition" from a user-owned / into the root-owned /run and
  # does not create /run/pifinder, so every update fails. Activation scripts
  # run at boot before systemd starts, so tmpfiles sees the repaired owners.
  # Only the directories change owner, not their contents.
  system.activationScripts.fix-root-ownership = ''
    for d in / /boot /home /nix /var /var/lib; do
      if [ -d "$d" ] && [ "$(stat -c %u "$d")" != 0 ]; then
        echo "fix-root-ownership: $d is not owned by root, repairing"
        chown 0:0 "$d" || true
      fi
    done
  '';

  # Login credentials carried over by the Pi OS migration (ADR 0039): the
  # pifinder password hash, the SSH host keys (so clients see the same host)
  # and nothing else. Applied once, before sshd starts; NixOS keeps both
  # across generations (mutable users, /etc/ssh), so the staged copies are
  # deleted after use. The migration system boots first and must already
  # answer SSH as the old host.
  systemd.services.pifinder-migrated-credentials = {
    description = "Apply login credentials carried over by the migration";
    before = [ "sshd.service" ];
    wantedBy = [ "multi-user.target" ];
    unitConfig.ConditionPathIsDirectory = "/var/lib/pifinder/migrated";
    serviceConfig.Type = "oneshot";
    path = with pkgs; [ coreutils shadow ];
    script = ''
      dir=/var/lib/pifinder/migrated
      if [ -s "$dir/password-hash" ]; then
        hash=$(cat "$dir/password-hash")
        # libxcrypt in nixpkgs checks only the strong hash types. Pi OS
        # images store "solveit" as SHA-256 crypt ($5$), which NixOS cannot
        # check: with that hash no password works. Keep the NixOS default
        # then; it is the same password.
        case "$hash" in
          '$y$'* | '$gy$'* | '$7$'* | '$2b$'* | '$6$'*)
            printf 'pifinder:%s\n' "$hash" | chpasswd -e ;;
          *)
            echo "carried password hash is not a strong type; the default stays" ;;
        esac
      fi
      for key in "$dir"/ssh/ssh_host_*; do
        [ -e "$key" ] || continue
        install -o root -g root -m 600 "$key" /etc/ssh/
        case "$key" in *.pub) chmod 644 "/etc/ssh/$(basename "$key")" ;; esac
      done
      rm -rf "$dir"
    '';
  };

  # A pifinder password hash that libxcrypt cannot check (not a strong type)
  # makes every login fail, on SSH and in the web UI. Devices migrated before
  # the filter above have one. Set the default password again; nobody can log
  # in with such a hash anyway. A locked (!, *) or empty field is left as is.
  systemd.services.pifinder-password-usable = {
    description = "Reset a pifinder password hash that cannot be checked";
    after = [ "pifinder-migrated-credentials.service" ];
    before = [ "sshd.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig.Type = "oneshot";
    path = with pkgs; [ coreutils gawk shadow ];
    script = ''
      hash=$(awk -F: '$1 == "pifinder" {print $2}' /etc/shadow)
      case "$hash" in
        "" | '!'* | '*'* | '$y$'* | '$gy$'* | '$7$'* | '$2b$'* | '$6$'*) exit 0 ;;
      esac
      echo "pifinder password hash cannot be checked; setting the default password"
      printf 'pifinder:solveit\n' | chpasswd
    '';
  };

  # ---------------------------------------------------------------------------
  # Remove the ext4 rollback image after the migration (ADR 0039)
  # ---------------------------------------------------------------------------
  # btrfs-convert leaves ext2_saved, an image of the old ext4 that holds the
  # space of Pi OS and its data. Once a generation on btrfs is confirmed, the
  # migration is not rolled back any more, so delete it to free the space.
  #
  # The watchdog orders itself after multi-user.target. A unit that
  # multi-user.target wants, with no ordering of its own to that target, gets
  # an implicit "multi-user.target after this unit"; with "after watchdog"
  # that is a cycle, and systemd deletes the job at each boot. So the
  # services that run after the watchdog name multi-user.target in after.
  systemd.services.pifinder-migration-cleanup = {
    description = "Remove the ext4 rollback image left by the migration";
    after = [ "multi-user.target" "pifinder-watchdog.service" ];
    wantedBy = [ "multi-user.target" ];
    unitConfig.ConditionPathIsDirectory = "/ext2_saved";
    serviceConfig = {
      Type = "oneshot";
      Nice = 19;
      IOSchedulingClass = "idle";
    };
    path = with pkgs; [ btrfs-progs coreutils gnugrep ];
    script = ''
      CURRENT=$(readlink -f /run/current-system)
      if ! grep -qxF "$CURRENT" /var/lib/pifinder/confirmed-generations 2>/dev/null; then
        echo "$CURRENT is not confirmed yet; keeping /ext2_saved"
        exit 0
      fi
      btrfs subvolume delete /ext2_saved
    '';
  };

  # ---------------------------------------------------------------------------
  # Compact the btrfs chunks once after the migration (ADR 0039)
  # ---------------------------------------------------------------------------
  # btrfs-convert maps the ext4 layout into btrfs chunks. When the Pi OS files
  # and ext2_saved are gone, many data chunks are only partly used. A balance
  # of the chunks under 50 % use packs them and gives the space back as
  # unallocated space, so that metadata can still grow. It runs once, in the
  # boot where the cleanup deleted /ext2_saved (or any later boot), on a
  # confirmed generation. An upgrade stops it (nixos_upgrade.py); the stop
  # signal cancels the balance, no marker is written, and the next boot
  # starts again.
  #
  # No defragment. After the migration the only converted data is
  # PiFinder_data, and nearly all of it is catalog JPEGs (about 5 GB). JPEG
  # does not compress, and ext4 kept those files in few extents, so
  # "defragment -czstd" would write gigabytes to the SD card for no gain. The
  # system files were written after the conversion, so they are btrfs
  # extents with zstd already.
  #
  # Each step logs its start, end, duration and the load average (every
  # 30 s) to the journal and to PiFinder_data/logs/btrfs-tidy.log.
  systemd.services.pifinder-btrfs-tidy = {
    description = "Compact btrfs chunks once after the migration";
    after = [
      "multi-user.target"
      "pifinder-watchdog.service"
      "pifinder-migration-cleanup.service"
    ];
    wantedBy = [ "multi-user.target" ];
    unitConfig = {
      ConditionPathExists = [ "!/var/lib/pifinder/btrfs-tidy-done" "!/ext2_saved" ];
    };
    serviceConfig = {
      Type = "oneshot";
      Nice = 19;
      IOSchedulingClass = "idle";
      CPUWeight = 20;
    };
    path = with pkgs; [ btrfs-progs coreutils gnugrep systemd util-linux ];
    script = ''
      LOG=/home/pifinder/PiFinder_data/logs/btrfs-tidy.log
      MARKER=/var/lib/pifinder/btrfs-tidy-done
      log() {
        echo "$*"
        echo "$(date -u +%FT%TZ) $*" >> "$LOG" 2>/dev/null || true
      }
      load() { cut -d' ' -f1-3 /proc/loadavg; }

      if [ "$(stat -f -c %T /)" != btrfs ]; then
        touch "$MARKER"
        exit 0
      fi
      CURRENT=$(readlink -f /run/current-system)
      if ! grep -qxF "$CURRENT" /var/lib/pifinder/confirmed-generations 2>/dev/null; then
        log "$CURRENT is not confirmed yet; balance at a later boot"
        exit 0
      fi
      if systemctl is-active --quiet pifinder-upgrade.service; then
        log "an upgrade runs; balance at a later boot"
        exit 0
      fi

      log "before: $(btrfs filesystem usage -b / | grep -E 'Device (allocated|unallocated)|Used:' | tr -s ' \t' ' ' | tr '\n' ';')"
      log "balance start, load $(load)"
      ( while sleep 30; do log "balance running, load $(load)"; done ) &
      sampler=$!
      start=$(date +%s)
      rc=0
      out=$(btrfs balance start -dusage=50 -musage=50 / 2>&1) || rc=$?
      kill "$sampler" 2>/dev/null || true
      log "balance end rc=$rc after $(( $(date +%s) - start )) s, load $(load): $out"
      log "after: $(btrfs filesystem usage -b / | grep -E 'Device (allocated|unallocated)|Used:' | tr -s ' \t' ' ' | tr '\n' ';')"
      if [ "$rc" -ne 0 ]; then
        exit 0
      fi
      touch "$MARKER"
    '';
  };
}
