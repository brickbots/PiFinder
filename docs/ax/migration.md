# Migration architecture: Raspberry Pi OS → NixOS

Companion to [`migration/CONTEXT.md`](./migration/CONTEXT.md): how a deployed PiFinder converts itself, in place, from a Raspberry Pi OS install to NixOS. The whole mechanism lives on `main`; the artifact it consumes (the **migration tarball**) and everything that happens after the reboot belong to the [NixOS](./nixos/CONTEXT.md) context.

The defining constraint: a running OS cannot reformat the SD card it booted from. The migration sidesteps this by doing the destructive work from a throwaway **initramfs** that lives entirely in RAM, so the card it rewrites is not the card it is running from.

## 1. The flow at a glance

```
 Raspberry Pi OS                          initramfs (RAM)                 NixOS
 ───────────────                          ───────────────                 ─────
 Software screen                          /init runs:
   ├─ migration gate (auto), or             save WiFi + PiFinder_data →RAM
   └─ migration enable (7×SQUARE)            copy tarball              →RAM
        │                                    format p1 (FAT) + p2 (ext4)
        ▼                                    unpack tarball → p2, boot → p1
   UIMigrationConfirm  (warn, size)          restore WiFi + user data
        │                                    expand + resize p2
        ▼                                    reboot ─────────────────────►  first boot
   UIMigrationProgress
        │   sys_utils.start_nixos_migration()
        ▼
   nixos_migration.sh:
     pre-flight → download → verify
     build initramfs → /boot
     edit config.txt → reboot ──────────►  (kernel loads initramfs)
```

Two scripts and one calculator do the work, all under `python/scripts/`:

- `nixos_migration.sh` — runs **on Raspberry Pi OS**: validate, download, stage the initramfs, arrange for the next boot to use it, reboot.
- `nixos_migration_init.sh` — the initramfs `/init`: runs **from RAM** and performs the actual reflash.
- `nixos_migration_calc.py` — the single source of truth for **pre-flight checks** (eligibility).

The UI side is in `python/PiFinder/ui/software.py`; the launch shim is `sys_utils.start_nixos_migration`.

## 2. Triggering: gate vs. enable

The Software screen (`UISoftware`) reaches the migration two ways, both ending in the same confirm → progress flow:

- **Migration gate** — `get_release_version()` fetches `migration_gate.json` from the `release` branch. If `nixos_for_everyone` is true, it builds the version info from the gate's `nixos_url` and triggers automatically. This is the fleet-wide rollout lever: one edit to one file on `release` opens (or closes) the migration for every device that checks in.
- **Migration enable** — pressing **SQUARE** seven times on the Software screen calls `_trigger_migration` directly, regardless of the gate. The early-adopter path.

`_trigger_migration` pushes `UIMigrationConfirm` (a warning screen showing the target version and the download size, `migration_size_mb`), and only on explicit confirmation does it push `UIMigrationProgress`, whose `_start_migration` calls `sys_utils.start_nixos_migration(version_info)`.

`start_nixos_migration` refuses to proceed without a SHA-256 for the tarball (from `migration_sha256_url` or a hardcoded `migration_sha256`) — there is no "migrate an unverified blob" path. It then launches `nixos_migration.sh` in the background, passing the URL, the checksum, a progress file, and the live **display class and resolution** so the initramfs knows which panel to draw on.

## 3. Pre-flight: an all-or-nothing gate

`nixos_migration_calc.py` is the one place that decides whether a device may migrate. `nixos_migration.sh` runs it first (`--json`); a non-zero exit aborts before anything is downloaded or touched. `all_ok` is the AND of every check:

| Check | Requirement | Why |
| ----- | ----------- | --- |
| Model | `Raspberry Pi 4` | The NixOS image and initramfs paths are built and tested for the Pi 4. |
| RAM | ≥ 1800 MB | The whole migration runs from RAM — tarball + backups + tools must fit. |
| SD size | ≥ 16 GB | The NixOS closure needs the room. |
| SD layout | stock 2-partition (`/dev/mmcblk0p1` + `p2`, root on `p2`) | The initramfs hardcodes these device paths and blindly extends `p2`. |
| Free space | ≥ 1.5 GB | Room to download the tarball onto the running system first. |
| WiFi mode | `Client` | The migration must reach the network for the download (Access Point mode can't). |
| Display | `DisplaySSD1351` 128×128 or `DisplaySSD1333` 176×176 | The **migration progress display** renderer supports only these. |

Note the display list is the *initramfs renderer's* capability, not the main app's — a panel the app supports but the progress binary can't draw on still fails pre-flight.

## 4. Staging the initramfs (still on Raspberry Pi OS)

`nixos_migration.sh` downloads the tarball to `~pifinder/pifinder-nixos-migration.tar.zst` (reusing a cached copy if its checksum matches), verifies the SHA-256, then assembles a minimal initramfs in `/tmp/nixos_initramfs`:

- **busybox** (sh, mount, dd, tar, cp…) plus the dynamically-linked filesystem tools it can't supply: `e2fsck`, `resize2fs`, `mke2fs`/`mkfs.ext4`, `mkfs.vfat`, `sfdisk`, `zstd` — each copied with its shared libraries, plus the dynamic linker.
- The static `migration_progress` binary and the **SPI kernel modules** (`spi-bcm2835`, `spidev`, decompressed if shipped `.ko.xz`/`.gz`/`.zst`) so the OLED can be driven with no userland.
- `nixos_migration_init.sh` as `/init`, and a `migration_meta` file recording the tarball path/size, the `PiFinder_data` path, and the display class/resolution.

It `cpio | gzip`s this into `/boot/initramfs-migration.gz`, drops a `/boot/nixos_migration` flag file (which survives the root reformat because it lives on the FAT boot partition), backs up `config.txt` to `config.txt.premigration`, and appends `initramfs initramfs-migration.gz followkernel`. The **commit point** is this `config.txt` edit: after the reboot, the kernel loads our initramfs instead of the normal root.

## 5. The reflash (initramfs, from RAM)

`nixos_migration_init.sh` runs as PID 1 with no real root filesystem. Its sequence:

1. **Bring up the panel.** A single long-lived `migration_progress --serve` reads stage updates from a FIFO held open on fd 3, so the OLED redraws in place and never blanks between stages (a fresh process per stage would re-assert the panel reset line). `trap '' PIPE` ensures a dead display process can never abort the migration — the display is best-effort, the migration is not.
2. **Validate.** Confirm the `/boot/nixos_migration` flag, re-read `migration_meta`, and check available RAM against tarball size + a 150 MB margin.
3. **Stage to RAM.** Mount the old root read-only and copy out the **preserved data**: WiFi (`wpa_supplicant.conf` and any NetworkManager `system-connections`) and `PiFinder_data` (root-level files, `obslists/`, with `pifinder.log` truncated to its last 1000 lines so a giant log can't exhaust RAM). The old `/etc/hostname` is bridged into `PiFinder_data/hostname` (Pi OS keeps it in `/etc`; NixOS reads it from `PiFinder_data`). A second RAM check covers tarball + backup + 150 MB before anything destructive.
4. **Copy the tarball to RAM and unmount the old root.** From here the old system is gone.
5. **Repartition and format.** Expand `p2` to fill the disk **before** formatting (`sfdisk -N 2 --no-reread` then `blockdev --rereadpt`) — re-reading the partition table *after* a freshly-written FAT can corrupt it. Then `mkfs.vfat -F32 -n FIRMWARE` on `p1` and `mkfs.ext4 -L NIXOS_SD` on `p2`.
6. **Unpack.** `zstd -d | tar x` the tarball onto the new ext4 root, hoist `rootfs/`'s contents to the partition root, and copy the `boot/` tree onto the FAT partition — verifying `extlinux/extlinux.conf` actually landed, since that file is what U-Boot reads. `chown -R 0:0` the `/nix/store` while the root is still writable: NetworkManager refuses to load plugin files not owned by root, so a non-root store silently kills WiFi on NixOS.
7. **Restore.** Rewrite each preserved WiFi network as a NetworkManager keyfile (SSID hex-encoded, PSK keyfile-escaped, filename sanitized so a hostile SSID can't escape the directory), restore `PiFinder_data`, and `chown` it to `1000:100` — the `pifinder` user's UID/GID on NixOS (different from Raspberry Pi OS).
8. **Finalize.** `e2fsck -f` + `resize2fs` the root, re-verify `extlinux.conf` survived, and `reboot -f` into NixOS.

## 6. Failure handling and the point of no return

Before step 5, every failure is safe: `nixos_migration.sh`'s `ERR` trap and the initramfs `fail()` write a `FAILED` status and stop, and the original `config.txt.premigration` is still recoverable. After the partitions are formatted, there is no rollback — a failure there leaves a half-written card. This asymmetry is *why* pre-flight and the two RAM checks are strict and run entirely before the first destructive step: the design front-loads everything that can refuse the migration so that the irreversible part rarely runs on a device that can't finish it. On a hard failure the initramfs drops to a shell (and shows `FAILED` on the OLED) rather than rebooting into nothing. Recovery from a botched card is out-of-band: reflash from an **image build** (`.img.zst`) or the user's own backup.

## 7. Artifacts and the hand-off

The migration consumes `pifinder-migration-vX.Y.Z.tar.zst` — `boot/` + `rootfs/`, self-contained, unpacked directly onto the card (independent of the Attic binary cache; see the NixOS context's [ADR 0001](./nixos/adr/0001-attic-binary-cache.md)). This is **not** the `pifinder-vX.Y.Z.img.zst` **SD image** used to flash a blank card; both are cut from the same release closure but do different jobs. Once the device reboots into NixOS, Migration is finished forever and all further updates flow through the NixOS context's **system update** channels.

## 8. Gotchas

- **Tarball ≠ image.** `…-migration-….tar.zst` is unpacked in place by an existing device; `….img.zst` is flashed onto a blank card. Never conflate them.
- **One-way.** There is no in-product route back to Raspberry Pi OS. The only "undo" is reflashing a card.
- **The progress display is a separate static binary** precisely because the app — and then the OS — is gone during the wipe. It is not the PiFinder UI.
- **Expand before format.** Reordering steps 5's expand/format corrupts the FAT partition.
- **Root-owned `/nix/store` or no WiFi.** NetworkManager silently refuses a non-root-owned store; the initramfs normalizes ownership, with a boot-time service as backstop on the NixOS side.
- **UID/GID changes across the boundary** — `pifinder` is `1000:100` on NixOS — so restored data is re-chowned, not copied verbatim.
- **Pre-flight display support is the initramfs renderer's, not the app's.** They are checked independently.
