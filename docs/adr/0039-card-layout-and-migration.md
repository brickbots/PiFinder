# A NixOS card is FAT firmware plus a btrfs root; the migration converts the Raspbian root in place

**Status:** decided 2026-09-26. The system is btrfs-only on `nixos`. The migration and the SD images still write ext4 `NIXOS_SD`, and the plan in `docs/ax/nixos/btrfs-and-data-packs-plan.md` changes them.

## Card layout

Every NixOS PiFinder card has two partitions:

- **Partition 1:** FAT, label `FIRMWARE`. It holds only what the boot ROM and the GPU firmware must read: `config.txt`, `start*.elf`, the DTBs, the armstub and U-Boot. The boot ROM reads only FAT, so this partition must stay. It is written at install or migration, and again only by a firmware or U-Boot update.
- **Partition 2:** btrfs, label `PIFINDER_SD`. It holds everything else, including `/boot` with `extlinux.conf`, the kernels and the initrds. U-Boot reads them with `sysboot mmc 0:2`.

We use btrfs for the root because:

- it checksums data and metadata, so it finds a corrupt block and does not return it;
- its copy-on-write updates leave a file old or new after a power cut. `/boot` changes on each generation switch, so this matters;
- it gives reflink copies, compression and subvolume snapshots. The migration and the data packs use them ([ADR 0040](./0040-data-packs.md)).

The root is mounted as `/dev/mmcblk0p2`, not by label. The SD card and the eMMC of the Pi 4 and the CM4 are both `mmcblk0`.

`/home/pifinder/PiFinder_data` is its own subvolume. Everything else is on the top level. The system needs no subvolume, because NixOS generations give it rollback.

## Migration

The migration moves a Raspbian PiFinder to NixOS once. A Raspbian card runs ext4 and stays on 2.6.4 until it migrates. So no NixOS system needs ext4.

1. **Trigger:** the Software screen offers the migration when the flag `nixos_migration` in `migration_gate.json` on the upstream `release` branch is true. Pressing square 7 times offers it without the gate. Pi OS up to 2.6.3 reads only the old flag `nixos_for_everyone`, which stays false, so such a Pi must update to a version with the btrfs migration first.
2. **Prepare (Raspbian):** download the migration tarball of the chosen release, check its sha256, build a migration initramfs on the boot partition, add it to `config.txt`, and reboot.
3. **Convert (initramfs):** `btrfs-convert` changes partition 2 from ext4 to btrfs in place, so the files stay, `PiFinder_data/catalog_images` included. The initramfs then:
   - creates the `PiFinder_data` subvolume and reflink-copies the kept data into it;
   - deletes the Raspbian system files;
   - extracts the NixOS system from the tarball;
   - grows the file system if the partition was not grown;
   - formats partition 1 as FAT `FIRMWARE` and copies the firmware.

   The partition table stays as it is, so the FAT partition keeps its Raspbian size (256 or 512 MB).
4. **First boot:** a minimal migration system boots. It reads the update manifest, takes the newest entry of the best channel (stable, then beta, then the unstable trunk), downloads that full system, switches to it and reboots. The minimal system carries a built-in target only as a fallback when the manifest cannot be read.
5. **Cleanup:** after the first confirmed generation, a service deletes the `ext2_saved` subvolume that `btrfs-convert` left for rollback and runs a balance. Later, a background `btrfs filesystem defragment -r -czstd` compresses the old files.

**Tarball.** It holds the minimal migration system, not the full system, so it never goes stale: the full system comes from the manifest. CI builds it straight from the Nix closure (a `boot/` folder with the firmware and a `rootfs/` folder with the store paths), without an SD image and without a loop mount. It is published as an asset with a `.sha256` sidecar on each stable or beta release, and the manifest names it per entry as `migration_url`.

## Considered options

- **ext4 root (NixOS ADR 0007), superseded.** Atomic renames, but no checksums, reflinks or snapshots.
- **btrfs for everything, rejected.** The boot ROM cannot read btrfs.
- **Subvolumes for `/nix` and the system, rejected.** A snapshot of `/nix` holds gigabytes of old store paths, and generations already cover the system.
- **Root by label, rejected.** A build that names a label the card does not have stops in the initrd, before the watchdog runs. On 2026-09-26 a `NIXOS_SD` build left a `PIFINDER_SD` card with a black screen.
- **Format partition 2 with `mkfs.btrfs`, rejected.** Simpler, but it deletes the catalog images (up to 5 GB). They do not fit in RAM during a format.
- **Tarball cut from a loop-mounted SD image, rejected.** The image is only an intermediate step, and the loop mount needs `sudo` in CI.
- **Tarball with the full system, rejected.** About 1.4 GB per release, and it freezes the migrated version.
- **Tarball built once at a fixed URL, rejected.** It has no version, notes or checksum record.
- **A pinned store path in the tarball, rejected.** In the short-retention cache it is garbage-collected while the tarball is still published. In the retained cache, every test build stays for ever.

## Consequences

- The system supports only btrfs and vfat, and its initrd carries only btrfs. ext4 stays in the kernel config: removing it needs a kernel rebuild for a few kB.
- The upgrade refuses a build whose `etc/fstab` root does not match the mounted root (`check_root_mountable` in `nixos_upgrade.py`). `pifinder-first-boot` must make the same check.
- U-Boot must read btrfs, because `extlinux.conf` and the kernels are on partition 2.
- The SD images must create btrfs `PIFINDER_SD` with the `PiFinder_data` subvolume, so flashed and migrated cards are the same apart from the FAT size.
- The upgrade can take a read-only snapshot of `PiFinder_data` before it switches, and restore it if a new version damages user data.
- Anything that reads the tarball must not assume the Raspbian layout: `boot/` is the firmware, and `rootfs/boot` holds the kernels and `extlinux.conf`. On 2026-07-05 the first real migration failed on this.
- The migration must write `/var/lib/pifinder/camera-type` from the Raspbian `config.txt`. `device.nix` expects it, and no migration code writes it today.
- `btrfs-convert` needs free space and RAM. It must be tested on full cards and on a Pi with 1.8 GB of RAM before the gate opens.

Replaces NixOS ADR 0003 and 0004 (migration tarball) and 0007 (boot on ext4).
