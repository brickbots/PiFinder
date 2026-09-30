{ lib, pkgs, ... }:
# SD image layout (ADR 0039): FAT firmware partition FIRMWARE and a btrfs
# root PIFINDER_SD with the PiFinder_data subvolume, the same layout the
# migration makes. Imported only by the image builds (includeSDImage).
{
  sdImage.rootFilesystemCreator = ./pkgs/make-pifinder-btrfs-fs.nix;
  sdImage.rootVolumeLabel = "PIFINDER_SD";

  # sd-image.nix mounts the root by label as ext4. PiFinder mounts the
  # partition, whatever its label (see nixos/services.nix).
  fileSystems."/" = lib.mkForce {
    device = "/dev/mmcblk0p2";
    fsType = "btrfs";
    options = [ "compress=zstd:1" "noatime" ];
  };

  # sd-image.nix grows the root with resize2fs, which is for ext4 only.
  sdImage.expandOnBoot = false;

  # First boot: grow partition 2 to the end of the card, then the btrfs on
  # it. Runs once: register-nix-paths deletes /nix-path-registration.
  systemd.services.pifinder-grow-root = {
    description = "Grow the btrfs root to fill the SD card";
    unitConfig = {
      DefaultDependencies = false;
      ConditionPathExists = "/nix-path-registration";
    };
    wantedBy = [ "sysinit.target" ];
    before = [
      "sysinit.target"
      "shutdown.target"
      "register-nix-paths.service"
    ];
    after = [ "local-fs.target" ];
    conflicts = [ "shutdown.target" ];
    restartIfChanged = false;
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    path = with pkgs; [ util-linux gawk parted btrfs-progs ];
    script = ''
      rootPart=$(findmnt -n -o SOURCE /)
      rootPart=''${rootPart%%[*}
      bootDevice=$(lsblk -npo PKNAME "$rootPart")
      partNum=$(lsblk -npo MAJ:MIN "$rootPart" | awk -F: '{print $2}')

      echo ",+," | sfdisk -N"$partNum" --no-reread "$bootDevice"
      partprobe
      btrfs filesystem resize max /
    '';
  };
}
