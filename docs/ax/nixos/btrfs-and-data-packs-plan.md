# Plan: btrfs cards, btrfs migration and data packs

The design is in [ADR 0039](../../adr/0039-card-layout-and-migration.md) (card layout and migration) and [ADR 0040](../../adr/0040-data-packs.md) (data packs). This plan lists the work in order. Each step is one PR against `nixos`, unless it says otherwise. A step starts only when the steps it needs are merged.

## Done (2026-09-26)

- #70: the upgrade refuses a build whose root it cannot mount.
- #72: the `nixos` system is btrfs-only, with the root on `/dev/mmcblk0p2`.

## Part A: btrfs cards and migration

**A1. First-boot root check.** `pifinder-first-boot` (`nixos/device.nix`) runs `check_root_mountable` before it switches. Needs nothing. Check: a unit test for the refusal, and a first boot in the e2e harness if possible.

**A2. U-Boot reads btrfs.** Confirm that `ubootSD` (`flake.nix`) has `CONFIG_FS_BTRFS` and that `sysboot mmc 0:2` finds `extlinux.conf` on btrfs. Add the option if it is missing. Needs nothing. Check: build `ubootSD` and read its config; boot a btrfs card.

**A3. Migration system on btrfs.** `mkPifinderMigration` and `nixos/device.nix`: root `/dev/mmcblk0p2` as btrfs, btrfs in the initrd, `btrfs-progs` in the system. Needs A2. Check: `nix eval` of the root; build the initrd and read its file system list.

**A4. SD images on btrfs.** `images.pifinder` and `images.pifinder-migration`: `sdImage.rootFilesystemCreator = make-btrfs-fs.nix`, label `PIFINDER_SD`, the `PiFinder_data` subvolume, and a `fileSystems."/"` override (the sd-image module fixes it to ext4). Needs A2 and A3. Open: does `make-btrfs-fs.nix` create subvolumes, or must a first-boot service create it? Check: build the image, loop-mount it, and read the label, the file system and the subvolumes; boot it on a Pi.

**A5. Tarball from the closure.** A derivation that writes `boot/` (firmware, U-Boot, `config.txt`) and `rootfs/` (the migration system's store paths, the registration file, the first-boot target), packed as `.tar.zst`. `release.yml` uses it, with no loop mount. The 800 MB budget and the `.sha256` sidecar stay. Needs A3. Check: compare the file list with a tarball cut from today's image; run the migration init against it in a test (A7).

**A6. Migration init converts in place.** `python/scripts/nixos_migration.sh` and `nixos_migration_init.sh`. This goes to the Raspbian line on `brickbots/PiFinder` `main`, through the migration PR. The steps:
- `btrfs-progs` in the initramfs; `e2fsck`, `resize2fs` and `mke2fs` go.
- `btrfs-convert -L PIFINDER_SD /dev/mmcblk0p2`.
- Create the `PiFinder_data` subvolume and reflink-copy the kept data into it.
- Delete the Raspbian system files, extract the tarball's `rootfs/`, and resize with `btrfs filesystem resize max` if the partition grew.
- Format partition 1 as FAT `FIRMWARE`, copy the firmware, and write `/var/lib/pifinder/camera-type` from the Raspbian `config.txt`.
- Before the point of no return, a failure restores `config.txt` and boots Raspbian. After it, `btrfs-convert -r` can still roll back while `ext2_saved` exists. Decide if the init uses that.
- The preflight in `nixos_migration_calc.py` checks the free space that `btrfs-convert` needs.

Needs A3 and A5. Open: the free space and RAM that `btrfs-convert` needs on a full 16 GB and 32 GB card. Check: A7.

**A7. Migration test on a spare Pi.** A Raspbian card at 2.6.4 with `catalog_images` and observations, then the migration. Check:
- the images and observations are kept;
- the camera is right;
- the first boot switches to the full system;
- a second card that is nearly full;
- the RAM peak on 1.8 GB.

Needs A1 to A6 and a spare Pi. Nothing opens the gate before this passes.

**A8. Cleanup after migration.** A service that runs after the first confirmed generation: delete `ext2_saved`, run a balance, and start `btrfs filesystem defragment -r -czstd` at low priority. Needs A6. Check: on the A7 card, the free space before and after.

**A9. Snapshot of user data before an upgrade.** `nixos_upgrade.py` takes a read-only snapshot of `PiFinder_data` before it switches, and keeps the last two. The restore path (a watchdog step or a manual step) is decided in this PR. Needs A4 or A6 (the subvolume). Check: unit tests; an upgrade on a btrfs card.

**A10. U-Boot bootcount (ADR 0038 gap).** `bootcount` with `altbootcmd` in `ubootSD`. The watchdog's confirm step resets the counter. Needs A2. Check: install a build that stops in the initrd on a test card, and see that the third boot starts the previous entry.

## Part B: data packs

**B1. Chunk format facts.** Read the Attic source for the FastCDC version, the chunk sizes, the chunk hash and when Attic does not chunk (the size threshold). Write the result into ADR 0040. Needs nothing. No code.

**B2. Catalog image shards in CI.** A job that builds the image shards as fixed-output derivations from the image source. It runs only when the images change, and pushes the shards and the pack to Attic. The pack's store path and size go into the update manifest (`update_manifest.py`, a `packs` section). Needs nothing. Open: where the 5 GB of images come from in CI, and how to split them into shards below 256 MiB (by catalog and object range). Check: the manifest has the pack, and `nix path-info` on the cache shows it signed.

**B3. `pifinder-packs` service.** `/var/lib/pifinder/packs.json` (the selection), one profile per pack, `nix build --max-jobs 0`, `nix-env --set`, removal and garbage collection, and a status file. It runs on a selection change, when the network comes up, and after a system update. Needs B2. Check: unit tests; on a Pi, get and remove a pack and read the free space.

**B4. App reads images from the pack.** `cat_images.py` reads from `/nix/var/nix/profiles/packs/catalog-images`, then from the old `PiFinder_data/catalog_images`, then from the CDN per object. It shows "No image / Download at: Tools > Data packs" and "Image downloading". Needs B3. Check: UI tests for each state.

**B5. Tools > Data packs screen.** Size, free space, "Get", percentage, "Installed", "Needs <size>". Nothing downloads before "Get". Needs B3. Check: UI module tests; on a Pi, a lean card.

**B6. Keep the images of a migrated card.** A one-time service that arranges the kept files in the shape of each shard, runs `nix-store --add-fixed --recursive sha256` with reflink copies, and turns the pack on if all shards match. Needs B2, B3 and A6. Check: on the A7 card, the pack installs with no download.

**B7. Chunk transfer.** A server endpoint beside the differ (the chunk list of a NAR, and single chunks), and a compiled helper on the Pi (FastCDC as in B1). `pifinder-packs` uses it before `nix build`, with the local NARs and files as the chunk source. Any failure falls back to a normal download. Needs B1 and B3. Check: an e2e test like `nixos/tests/delta-e2e`, with a pack where a few images changed; the bytes downloaded and the memory peak.

**B8. Full and lean SD images.** The full image has the default packs in its store and their profiles. The lean image has none. Needs A4 and B2. Check: boot both; the full image shows the pack as installed.

**B9. Gaia deep chart pack.** On the `deepchart` branch, after B3 to B7. Not part of this plan.

## Order

A1, A2 and B1 can start now, in parallel. Then A3, A5 and A4, then A6 and A7. Part B can go in parallel with Part A up to B5. B6 needs the migration (A6).

## Open questions

- Does `make-btrfs-fs.nix` create subvolumes? (A4)
- How much free space and RAM does `btrfs-convert` need on a full card? (A6, A7)
- Where do the 5 GB of catalog images come from in CI, and how are they split into shards? (B2)
- Which Attic FastCDC version, settings and chunk hash? (B1)
- Where does the migration PR on the Raspbian side live: `brickbots/PiFinder` #657, which is on hold? (A6)
