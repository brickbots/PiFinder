# Migration Branch State

Branch: `migration`

## Overview

This branch implements an in-place OS migration from Raspberry Pi OS to NixOS on PiFinder hardware (Pi 4, 2GB+ RAM, 16GB+ SD). The user triggers it from the OLED UI; the system downloads a NixOS bootstrap tarball, builds a custom initramfs, reboots into it, repartitions the SD card, and extracts NixOS — all without removing the SD card.

The migration is gated behind a 7x square-button secret code on the SOFTWARE screen. The secret code directly triggers migration to v2.5.0 with hardcoded URL/SHA256. Regular users see the normal version.txt update flow (same as `main`).

## Migration Flow

```
User presses 7x Square on SOFTWARE screen
    │
    ▼
UIMigrationConfirm (OLED: version, size, "IRREVERSIBLE" warning)
    │ Confirm
    ▼
UIMigrationProgress (OLED: progress bar, status text)
    │ Calls sys_utils.start_nixos_migration()
    ▼
nixos_migration.sh (Phase 1: RPi OS, runs as background bash)
    ├─ Install deps (e2fsprogs, dosfstools, fdisk)
    ├─ Pre-flight checks via nixos_migration_calc.py
    │    (Pi4? RAM>=1800MB? SD>=16GB? WiFi=Client?)
    ├─ Download tarball (349MB) with progress → JSON file
    ├─ Verify SHA256
    ├─ Build initramfs:
    │    busybox + e2fsck + resize2fs + mke2fs + mkfs.vfat + sfdisk
    │    + migration_progress (OLED C binary) + init script + metadata
    ├─ Stage initramfs to /boot
    ├─ Set initramfs= in config.txt
    └─ Reboot (5s countdown)
         │
         ▼
nixos_migration_init.sh (Phase 2: Initramfs, runs from RAM)
    ├─ Save WiFi credentials to RAM (wpa_supplicant → iwd format)
    ├─ e2fsck root
    ├─ Shrink root FS + partition (resize2fs + sfdisk)
    ├─ Copy tarball + PiFinder_data backup to freed staging area (raw dd)
    ├─ === POINT OF NO RETURN ===
    ├─ Format boot (FAT32) + root (ext4)
    ├─ Extract NixOS tarball to new root
    ├─ Populate boot partition
    ├─ Migrate WiFi to iwd format (early, before user data)
    ├─ Write resume metadata to /var/lib/pifinder-migration/
    ├─ Restore PiFinder_data from staging
    ├─ Expand partition to fill SD
    └─ reboot -f → boots into bootstrap NixOS (Phase 3, not in this branch)
```

## Files

### UI (python/PiFinder/ui/software.py)

Simple `UISoftware` from `main` (version.txt checker, Update/Cancel toggle) plus:
- `_UNLOCK_SEQUENCE` / `_record_key()` / `key_square()` — 7x square triggers migration
- `UIMigrationConfirm` — warning screen with version info, size, irreversibility notice
- `UIMigrationProgress` — progress bar + scrollable status text, polls `sys_utils`
- `UIReleaseNotes` / `_strip_markdown()` — fetches and renders markdown release notes

No manifest/channel infrastructure — that lives on the `nixos` branch.

### Migration Scripts

| File | Purpose |
|------|---------|
| `python/scripts/nixos_migration.sh` | Phase 1 (RPi OS): pre-flight, download, initramfs build, boot config, reboot |
| `python/scripts/nixos_migration_init.sh` | Phase 2 (initramfs): shrink/stage/format/extract/restore/expand |
| `python/scripts/nixos_migration_calc.py` | Pre-flight validator: Pi model, RAM, SD size, free space, WiFi mode |
| `python/scripts/migration_progress.c` | Standalone C OLED driver for initramfs (SSD1351 SPI, 5x7 font, progress bar) |
| `python/scripts/migration_progress` | Compiled aarch64 binary of above |

### Other Modified Files

| File | Change |
|------|--------|
| `python/PiFinder/sys_utils.py` | `start_nixos_migration()`, `get_migration_progress()` |
| `python/PiFinder/solver.py` | tetra3 path fix, `solution.pop()`, missing key guards |
| `python/PiFinder/utils.py` | `tetra3_dir` path correction |

### Tests

`python/tests/test_software.py` — `TestUpdateNeeded`, `TestUnlockSequence`, `TestStripMarkdown`

## Key Constants

| Constant | Value |
|----------|-------|
| Bootstrap tarball URL | `mrosseel/PiFinder` release `v2.5.0-bootstrap` |
| SHA256 | `d5e5dc7bfde57bb958d0dc55804af6fb14265f12d9e27a02da0385847f9ba742` |
| Tarball size | 349 MB |
| Staging area | 8 GB at end of SD card |
| Min RAM | 1800 MB (2GB Pi reports ~1849MB) |
| Min SD | 16 GB |
| Secret code | 7x square button |
| Progress file | `/tmp/nixos_migration_progress` (JSON: percent + status) |
| OLED binary | SSD1351 via SPI0.0, DC=GPIO24, RST=GPIO25, 128x128 BGR565 |

## Architecture Notes

- **Progress pipeline**: `nixos_migration.sh` writes JSON to progress file → `sys_utils.get_migration_progress()` reads it → `UIMigrationProgress.update()` polls it → renders on OLED
- **Initramfs OLED**: compiled C binary included in initramfs, called by init script at each stage
- **WiFi migration**: wpa_supplicant.conf parsed and converted to iwd format — done early in initramfs before user data restore so network recovery is possible if restore fails
- **Resume support**: metadata written to `/var/lib/pifinder-migration/` on new root so Phase 3 (bootstrap NixOS, not in this branch) can resume if interrupted
- **Data staging**: raw `dd` to write tarball + backup to freed space at end of SD (after shrinking root), then reads it back after formatting — avoids needing double the disk space
